"""
AI Settings Dialog - Tkinter version for Translation App
=========================================================
Dynamic Model Manager, API Key Pool Manager & Playground for testing AI connections.
Supports:
- Waterfall model strategy (try models in order)
- API Key rotation (cycle through multiple keys on quota errors)
- Model testing playground
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Optional

from translation_app.core.ai_service import get_config_manager, test_single_model_connection


class AISettingsDialog(tk.Toplevel):
    """Settings dialog for AI configuration with API Key rotation support."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.config_manager = get_config_manager()
        self.test_thread = None
        
        self.title("⚙️ AI Settings & Playground")
        self.geometry("820x650")
        self.resizable(True, True)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._setup_ui()
        self._load_data()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _setup_ui(self):
        """Initialize UI components."""
        # Main container with scrollbar
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas, padding="10")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_frame = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        
        # Update canvas window width to match canvas width
        def _on_canvas_configure(event):
            self.canvas.itemconfig(self.canvas_frame, width=event.width)
        self.canvas.bind('<Configure>', _on_canvas_configure)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        main_frame = self.scrollable_frame
        
        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.bind_all("<MouseWheel>", _on_mousewheel)
        
        # =================================================================
        # API KEY POOL SECTION (NEW - supports rotation)
        # =================================================================
        api_pool_frame = ttk.LabelFrame(main_frame, text="🔑 API Key Pool (Xoay Tua Tự Động)", padding="10")
        api_pool_frame.pack(fill=tk.X, pady=(0, 10))
        
        # API Keys listbox
        keys_row = ttk.Frame(api_pool_frame)
        keys_row.pack(fill=tk.BOTH, expand=True)
        
        self.api_keys_listbox = tk.Listbox(keys_row, height=4, selectmode=tk.SINGLE)
        self.api_keys_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        keys_scrollbar = ttk.Scrollbar(keys_row, orient=tk.VERTICAL, command=self.api_keys_listbox.yview)
        keys_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.api_keys_listbox.config(yscrollcommand=keys_scrollbar.set)
        
        # API Key actions
        keys_btn_row = ttk.Frame(api_pool_frame)
        keys_btn_row.pack(fill=tk.X, pady=(5, 0))
        
        self.new_key_var = tk.StringVar()
        self.new_key_entry = ttk.Entry(keys_btn_row, textvariable=self.new_key_var, show="*", width=40)
        self.new_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.show_keys_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(keys_btn_row, text="👁️", variable=self.show_keys_var,
                        command=self._toggle_keys_visibility).pack(side=tk.LEFT, padx=2)
        ttk.Button(keys_btn_row, text="➕ Thêm Key", command=self._add_api_key).pack(side=tk.LEFT, padx=2)
        ttk.Button(keys_btn_row, text="🗑️ Xóa Key", command=self._remove_api_key).pack(side=tk.LEFT, padx=2)
        ttk.Button(keys_btn_row, text="🔄 Xoay Tua Thủ Công", command=self._manual_rotate).pack(side=tk.LEFT, padx=2)
        
        # Info label
        info_label = ttk.Label(api_pool_frame, 
                               text="💡 Tip: Thêm nhiều API Key để tự động xoay tua khi gặp lỗi quota/rate limit",
                               font=("Segoe UI", 9, "italic"), foreground="gray")
        info_label.pack(anchor=tk.W, pady=(5, 0))
        
        # =================================================================
        # MODEL LIST SECTION
        # =================================================================
        model_frame = ttk.LabelFrame(main_frame, text="📋 Danh sách Model (Waterfall Priority)", padding="10")
        model_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Treeview for models
        columns = ("model_id", "active", "timeout")
        self.model_tree = ttk.Treeview(model_frame, columns=columns, show="headings", height=8)
        self.model_tree.heading("model_id", text="Model ID")
        self.model_tree.heading("active", text="Active")
        self.model_tree.heading("timeout", text="Timeout (s)")
        self.model_tree.column("model_id", width=350)
        self.model_tree.column("active", width=80, anchor=tk.CENTER)
        self.model_tree.column("timeout", width=100, anchor=tk.CENTER)
        self.model_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Model action buttons
        btn_frame = ttk.Frame(model_frame)
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="⬆️ Lên", command=self._move_up).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⬇️ Xuống", command=self._move_down).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="✅/❌ Toggle", command=self._toggle_active).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ Xóa", command=self._delete_model).pack(side=tk.LEFT, padx=2)
        
        # Add model
        add_frame = ttk.Frame(model_frame)
        add_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.new_model_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.new_model_var, width=40).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(add_frame, text="➕ Thêm Model", command=self._add_model).pack(side=tk.LEFT)
        
        # =================================================================
        # PLAYGROUND SECTION
        # =================================================================
        play_frame = ttk.LabelFrame(main_frame, text="🧪 Playground - Test Connection", padding="10")
        play_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Model selector
        test_row = ttk.Frame(play_frame)
        test_row.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(test_row, text="Model:").pack(side=tk.LEFT)
        self.test_model_var = tk.StringVar()
        self.test_model_combo = ttk.Combobox(test_row, textvariable=self.test_model_var, width=40)
        self.test_model_combo.pack(side=tk.LEFT, padx=5)
        
        # Prompt
        prompt_row = ttk.Frame(play_frame)
        prompt_row.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(prompt_row, text="Prompt:").pack(side=tk.LEFT)
        self.test_prompt_var = tk.StringVar(value="Hello, are you alive?")
        ttk.Entry(prompt_row, textvariable=self.test_prompt_var, width=45).pack(side=tk.LEFT, padx=5)
        
        # Test button and result
        action_row = ttk.Frame(play_frame)
        action_row.pack(fill=tk.X, pady=(0, 5))
        self.test_btn = ttk.Button(action_row, text="🚀 Test Connection", command=self._run_test)
        self.test_btn.pack(side=tk.LEFT)
        self.test_result_var = tk.StringVar()
        ttk.Label(action_row, textvariable=self.test_result_var).pack(side=tk.LEFT, padx=10)
        
        # Response
        self.response_text = tk.Text(play_frame, height=3, wrap=tk.WORD)
        self.response_text.pack(fill=tk.X)
        
        # =================================================================
        # BOTTOM BUTTONS
        # =================================================================
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X)
        
        ttk.Button(bottom_frame, text="💾 Lưu Cấu Hình", command=self._save_config).pack(side=tk.LEFT, padx=2)
        ttk.Button(bottom_frame, text="🔄 Tải Lại", command=self._load_data).pack(side=tk.LEFT, padx=2)
        ttk.Button(bottom_frame, text="Đóng", command=self.destroy).pack(side=tk.RIGHT)
    
    # =========================================================================
    # API KEYS MANAGEMENT (NEW)
    # =========================================================================
    
    def _toggle_keys_visibility(self):
        """Toggle visibility of API keys in listbox and entry."""
        if self.show_keys_var.get():
            self.new_key_entry.config(show="")
            # Refresh listbox to show full keys
            self._refresh_api_keys_display(mask=False)
        else:
            self.new_key_entry.config(show="*")
            self._refresh_api_keys_display(mask=True)
    
    def destroy(self):
        """Clean up when dialog is closed."""
        self.unbind_all("<MouseWheel>")
        super().destroy()

    def _refresh_api_keys_display(self, mask: bool = True):
        """Refresh the API keys listbox display."""
        self.api_keys_listbox.delete(0, tk.END)
        for i, key in enumerate(self.config_manager.api_keys):
            if mask:
                display = f"🔑 Key {i+1}: {key[:8]}...{key[-4:]}" if len(key) > 12 else f"🔑 Key {i+1}: ***"
            else:
                display = f"🔑 Key {i+1}: {key}"
            
            # Mark current active key
            if i == 0:
                display = f"⭐ {display} (Active)"
            
            self.api_keys_listbox.insert(tk.END, display)
    
    def _add_api_key(self):
        """Add a new API key to the pool."""
        key = self.new_key_var.get().strip()
        if not key:
            messagebox.showwarning("Lỗi", "Vui lòng nhập API Key!")
            return
        
        # Check duplicate
        if key in self.config_manager.api_keys:
            messagebox.showwarning("Lỗi", "API Key này đã tồn tại!")
            return
        
        # Add to pool
        keys = self.config_manager.api_keys.copy()
        keys.append(key)
        self.config_manager.api_keys = keys
        self.config_manager.save_config()
        
        self.new_key_var.set("")
        self._refresh_api_keys_display(mask=not self.show_keys_var.get())
        messagebox.showinfo("Thành công", f"✅ Đã thêm API Key vào pool! Tổng: {len(keys)} keys")
    
    def _remove_api_key(self):
        """Remove selected API key from pool."""
        selection = self.api_keys_listbox.curselection()
        if not selection:
            messagebox.showwarning("Chưa chọn", "Vui lòng chọn một API Key để xóa!")
            return
        
        idx = selection[0]
        keys = self.config_manager.api_keys.copy()
        
        if messagebox.askyesno("Xác nhận", f"Xóa API Key #{idx+1}?"):
            keys.pop(idx)
            self.config_manager.api_keys = keys
            self.config_manager.save_config()
            self._refresh_api_keys_display(mask=not self.show_keys_var.get())
    
    def _manual_rotate(self):
        """Manually rotate to the next API key."""
        if self.config_manager.rotate_api_key():
            self._refresh_api_keys_display(mask=not self.show_keys_var.get())
            messagebox.showinfo("Xoay Tua", f"🔄 Đã chuyển sang API Key tiếp theo!")
        else:
            messagebox.showwarning("Lỗi", "Cần ít nhất 2 API Keys để xoay tua!")
    
    # =========================================================================
    # LEGACY API KEY (backward compatibility)
    # =========================================================================
    
    def _load_data(self):
        """Load config into UI."""
        self.config_manager.load_config()
        
        # Load API keys pool
        self._refresh_api_keys_display(mask=not self.show_keys_var.get())
        
        # Clear and reload model tree
        for item in self.model_tree.get_children():
            self.model_tree.delete(item)
        
        models = []
        for m in self.config_manager.waterfall_strategy:
            active = "✅" if m.get("is_active", True) else "❌"
            self.model_tree.insert("", tk.END, values=(m["model_id"], active, m.get("timeout", 10)))
            models.append(m["model_id"])
        
        self.test_model_combo["values"] = models
        if models:
            self.test_model_combo.current(0)
    
    def _get_selected_index(self) -> Optional[int]:
        selection = self.model_tree.selection()
        if not selection:
            messagebox.showwarning("Chưa chọn", "Vui lòng chọn một model!")
            return None
        return self.model_tree.index(selection[0])
    
    def _move_up(self):
        idx = self._get_selected_index()
        if idx is not None and idx > 0:
            items = list(self.model_tree.get_children())
            self.model_tree.move(items[idx], "", idx - 1)
    
    def _move_down(self):
        idx = self._get_selected_index()
        if idx is not None:
            items = list(self.model_tree.get_children())
            if idx < len(items) - 1:
                self.model_tree.move(items[idx], "", idx + 1)
    
    def _toggle_active(self):
        selection = self.model_tree.selection()
        if not selection:
            return
        item = selection[0]
        values = list(self.model_tree.item(item, "values"))
        values[1] = "❌" if values[1] == "✅" else "✅"
        self.model_tree.item(item, values=values)
    
    def _delete_model(self):
        selection = self.model_tree.selection()
        if not selection:
            return
        
        if messagebox.askyesno("Xác nhận", "Xóa model này?"):
            self.model_tree.delete(selection[0])
    
    def _add_model(self):
        model_id = self.new_model_var.get().strip()
        if not model_id:
            return
        # Check duplicate
        for item in self.model_tree.get_children():
            if self.model_tree.item(item, "values")[0] == model_id:
                messagebox.showwarning("Lỗi", f"Model '{model_id}' đã tồn tại!")
                return
        self.model_tree.insert("", tk.END, values=(model_id, "✅", 10))
        self.new_model_var.set("")
        self._update_combo()
    
    def _update_combo(self):
        models = [self.model_tree.item(item, "values")[0] for item in self.model_tree.get_children()]
        self.test_model_combo["values"] = models
    
    def _save_config(self):
        """Save all configuration including API keys pool."""
        # Note: API keys are saved when added/removed
        # Save model strategy only
        models = []
        for item in self.model_tree.get_children():
            vals = self.model_tree.item(item, "values")
            models.append({
                "model_id": vals[0],
                "is_active": vals[1] == "✅",
                "timeout": int(vals[2])
            })
        self.config_manager.waterfall_strategy = models
        
        if self.config_manager.save_config():
            messagebox.showinfo("Thành công", "✅ Đã lưu cấu hình!")
        else:
            messagebox.showerror("Lỗi", "❌ Không thể lưu cấu hình!")
    
    def _run_test(self):
        # Use the first API key from pool
        api_key = self.config_manager.api_key
        model_name = self.test_model_var.get().strip()
        prompt = self.test_prompt_var.get().strip() or "Ping"
        
        if not api_key:
            messagebox.showwarning("Lỗi", "Vui lòng thêm API Key vào pool!")
            return
        if not model_name:
            messagebox.showwarning("Lỗi", "Vui lòng chọn Model!")
            return
        
        self.test_btn.config(state=tk.DISABLED)
        self.test_result_var.set("🔄 Connecting...")
        self.response_text.delete("1.0", tk.END)
        
        def do_test():
            result = test_single_model_connection(api_key, model_name, prompt)
            self.after(0, lambda: self._on_test_result(result))
        
        self.test_thread = threading.Thread(target=do_test, daemon=True)
        self.test_thread.start()
    
    def _on_test_result(self, result: dict):
        self.test_btn.config(state=tk.NORMAL)
        if result.get("success"):
            self.test_result_var.set(f"✅ SUCCESS - {result['latency']}")
            self.response_text.insert("1.0", f"Response:\n{result.get('reply', '')}")
        else:
            self.test_result_var.set("❌ FAILED")
            self.response_text.insert("1.0", f"Error:\n{result.get('error', 'Unknown')}")
