from types import SimpleNamespace

import pytest

from translation_app.core.file_handlers import excel_com_handler
from translation_app.core.file_handlers.excel_com_handler import ExcelComHandler
from translation_app.core.file_translation_control import FileTranslationInterrupted, FileTranslationStopRequested
from translation_app.core.incremental_translation_cache import get_cache_path
from translation_app.utils.error_handler import FileProcessingError


class FakeFuture:
    def __init__(self, func, args):
        self._func = func
        self._args = args

    def result(self, timeout=None):
        return self._func(*self._args)


class FakeExecutor:
    def submit(self, func, *args):
        return FakeFuture(func, args)


class FakeTranslationService:
    timeout = 5

    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call
        self.executor = FakeExecutor()

    def translate_long_text(self, text, src_lang, dest_lang):
        self.calls.append(text)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("simulated provider failure")
        return f"[{dest_lang}:{text}]"

    def raise_if_file_translation_stopped(self):
        return None


class StopAfterChecksTranslationService(FakeTranslationService):
    def __init__(self, stop_after_checks):
        super().__init__()
        self.stop_after_checks = stop_after_checks
        self.stop_checks = 0

    def raise_if_file_translation_stopped(self):
        self.stop_checks += 1
        if self.stop_checks >= self.stop_after_checks:
            raise FileTranslationStopRequested("cancelled")


class FakeCell:
    def __init__(self, row, col, value):
        self.row = row
        self.col = col
        self.Value = value
        self.HasFormula = False
        self.Formula = value
        self.MergeCells = False
        self.Address = f"R{row}C{col}"


class FakeRange:
    def __init__(self, sheet):
        self._sheet = sheet
        self.Row = 1
        self.Column = 1
        self.Rows = SimpleNamespace(Count=1)
        self.Columns = SimpleNamespace(Count=len(sheet.cells))

    @property
    def Value(self):
        return tuple(tuple(cell.Value for cell in self._sheet.cells.values()))

    def Cells(self, row, col):
        return self._sheet.Cells(row, col)


class FakeSheet:
    def __init__(self, name, values):
        self.Name = name
        self.cells = {
            (1, col): FakeCell(1, col, value)
            for col, value in enumerate(values, start=1)
        }
        self.UsedRange = FakeRange(self)

    def Cells(self, row, col):
        return self.cells[(row, col)]

    def values(self):
        return [cell.Value for cell in self.cells.values()]


class FakeWorksheets:
    def __init__(self, sheets):
        self._sheets = sheets
        self.Count = len(sheets)

    def Item(self, index):
        return self._sheets[index - 1]


class FakeWorkbook:
    def __init__(self, sheets):
        self.Worksheets = FakeWorksheets(sheets)
        self.saved_as = None
        self.closed = False

    def SaveAs(self, path, FileFormat=None):
        self.saved_as = path

    def Close(self, SaveChanges=False):
        self.closed = True


class FakeWorkbooks:
    def __init__(self, workbook):
        self._workbook = workbook

    def Open(self, *args, **kwargs):
        return self._workbook


class FakeExcelApp:
    def __init__(self, workbook):
        self.Workbooks = FakeWorkbooks(workbook)
        self.quit_called = False

    def Quit(self):
        self.quit_called = True


def _install_fake_com(monkeypatch, workbook):
    fake_app = FakeExcelApp(workbook)
    monkeypatch.setattr(excel_com_handler, "COM_AVAILABLE", True)
    monkeypatch.setattr(
        excel_com_handler,
        "pythoncom",
        SimpleNamespace(CoInitialize=lambda: None, com_error=RuntimeError),
        raising=False,
    )
    monkeypatch.setattr(
        excel_com_handler,
        "win32com",
        SimpleNamespace(client=SimpleNamespace(Dispatch=lambda name: fake_app)),
        raising=False,
    )
    return fake_app


def _handler(service):
    handler = ExcelComHandler.__new__(ExcelComHandler)
    handler.translation_service = service
    handler.ocr_handler = None
    handler.job_manager = None
    handler.job_id = None
    handler._job_total_segments = 0
    return handler


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    import translation_app.core.incremental_translation_cache as incremental_cache

    monkeypatch.setattr(incremental_cache, "get_incremental_cache_dir", lambda: tmp_path / "cache")
    return tmp_path / "cache"


def test_excel_com_resume_skips_translated_cells(monkeypatch, tmp_path, isolated_cache):
    input_file = tmp_path / "source.xlsx"
    output_file = tmp_path / "translated.xlsx"
    input_file.write_bytes(b"workbook-v1")

    first_workbook = FakeWorkbook([FakeSheet("Sheet1", ["Alpha", "Beta", "Gamma"])])
    _install_fake_com(monkeypatch, first_workbook)
    first_service = FakeTranslationService(fail_on_call=3)

    with pytest.raises(FileProcessingError):
        _handler(first_service).translate(str(input_file), str(output_file), "en", "vi")

    cache_path = get_cache_path(str(input_file), "en", "vi", "excel_com")
    assert cache_path.exists()
    assert first_service.calls == ["Alpha", "Beta", "Gamma"]

    second_sheet = FakeSheet("Sheet1", ["Alpha", "Beta", "Gamma"])
    second_workbook = FakeWorkbook([second_sheet])
    _install_fake_com(monkeypatch, second_workbook)
    second_service = FakeTranslationService()

    _handler(second_service).translate(str(input_file), str(output_file), "en", "vi")

    assert second_service.calls == ["Gamma"]
    assert second_sheet.values() == ["[vi:Alpha]", "[vi:Beta]", "[vi:Gamma]"]
    assert not cache_path.exists()


def test_excel_com_cache_retained_on_failure(monkeypatch, tmp_path, isolated_cache):
    input_file = tmp_path / "source.xlsx"
    output_file = tmp_path / "translated.xlsx"
    input_file.write_bytes(b"workbook-v1")
    _install_fake_com(monkeypatch, FakeWorkbook([FakeSheet("Sheet1", ["Alpha", "Beta", "Gamma"])]))

    with pytest.raises(FileProcessingError):
        _handler(FakeTranslationService(fail_on_call=3)).translate(
            str(input_file),
            str(output_file),
            "en",
            "vi",
        )

    assert get_cache_path(str(input_file), "en", "vi", "excel_com").exists()


def test_excel_com_cache_cleared_on_complete(monkeypatch, tmp_path, isolated_cache):
    input_file = tmp_path / "source.xlsx"
    output_file = tmp_path / "translated.xlsx"
    input_file.write_bytes(b"workbook-v1")
    _install_fake_com(monkeypatch, FakeWorkbook([FakeSheet("Sheet1", ["Alpha", "Beta"])]))

    _handler(FakeTranslationService()).translate(str(input_file), str(output_file), "en", "vi")

    assert not get_cache_path(str(input_file), "en", "vi", "excel_com").exists()


def test_excel_com_cache_retained_on_cancel(monkeypatch, tmp_path, isolated_cache):
    input_file = tmp_path / "source.xlsx"
    output_file = tmp_path / "translated.xlsx"
    input_file.write_bytes(b"workbook-v1")
    _install_fake_com(monkeypatch, FakeWorkbook([FakeSheet("Sheet1", ["Alpha", "Beta", "Gamma"])]))

    with pytest.raises(FileTranslationInterrupted):
        _handler(StopAfterChecksTranslationService(stop_after_checks=5)).translate(
            str(input_file),
            str(output_file),
            "en",
            "vi",
        )

    assert get_cache_path(str(input_file), "en", "vi", "excel_com").exists()


def test_excel_com_source_workbook_change_does_not_reuse_cache(monkeypatch, tmp_path, isolated_cache):
    input_file = tmp_path / "source.xlsx"
    output_file = tmp_path / "translated.xlsx"
    input_file.write_bytes(b"workbook-v1")
    _install_fake_com(monkeypatch, FakeWorkbook([FakeSheet("Sheet1", ["Alpha", "Beta"])]))

    with pytest.raises(FileProcessingError):
        _handler(FakeTranslationService(fail_on_call=2)).translate(
            str(input_file),
            str(output_file),
            "en",
            "vi",
        )

    input_file.write_bytes(b"workbook-v2")
    changed_sheet = FakeSheet("Sheet1", ["Alpha", "Beta"])
    _install_fake_com(monkeypatch, FakeWorkbook([changed_sheet]))
    service = FakeTranslationService()

    _handler(service).translate(str(input_file), str(output_file), "en", "vi")

    assert service.calls == ["Alpha", "Beta"]
    assert changed_sheet.values() == ["[vi:Alpha]", "[vi:Beta]"]


def test_excel_com_target_language_change_does_not_reuse_cache(monkeypatch, tmp_path, isolated_cache):
    input_file = tmp_path / "source.xlsx"
    output_file = tmp_path / "translated.xlsx"
    input_file.write_bytes(b"workbook-v1")
    _install_fake_com(monkeypatch, FakeWorkbook([FakeSheet("Sheet1", ["Alpha", "Beta"])]))

    with pytest.raises(FileProcessingError):
        _handler(FakeTranslationService(fail_on_call=2)).translate(
            str(input_file),
            str(output_file),
            "en",
            "vi",
        )

    changed_sheet = FakeSheet("Sheet1", ["Alpha", "Beta"])
    _install_fake_com(monkeypatch, FakeWorkbook([changed_sheet]))
    service = FakeTranslationService()

    _handler(service).translate(str(input_file), str(output_file), "en", "fr")

    assert service.calls == ["Alpha", "Beta"]
    assert changed_sheet.values() == ["[fr:Alpha]", "[fr:Beta]"]
