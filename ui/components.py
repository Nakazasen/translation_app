"""
Reusable UI components for translation application
"""
import tkinter as tk
from typing import Callable, Optional, Dict


def create_styled_button(
    parent: tk.Widget,
    text: str,
    command: Optional[Callable] = None,
    colors: Optional[Dict[str, str]] = None,
    **kwargs
) -> tk.Button:
    """
    Create button with professional styling
    
    Args:
        parent: Parent widget
        text: Button text
        command: Command to execute on click
        colors: Color dictionary (if None, uses default)
        **kwargs: Additional button options
    
    Returns:
        Styled button widget
    """
    if colors is None:
        colors = {
            'navy': '#1e3a5f',
            'blue': '#4a90e2',
            'white': '#ffffff'
        }
    
    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=colors['navy'],
        fg=colors['white'],
        activebackground=colors['blue'],
        activeforeground=colors['white'],
        font=('Segoe UI', 10, 'bold'),
        relief='flat',
        borderwidth=0,
        padx=15,
        pady=10,
        cursor='hand2',
        **kwargs
    )
    return button


def create_language_combobox(
    parent: tk.Widget,
    textvariable: tk.StringVar,
    values: list,
    colors: Optional[Dict[str, str]] = None
) -> tk.ttk.Combobox:
    """
    Create language selection combobox
    
    Args:
        parent: Parent widget
        textvariable: StringVar to bind to
        values: List of language codes
        colors: Color dictionary (optional)
    
    Returns:
        Styled combobox widget
    """
    combobox = tk.ttk.Combobox(
        parent,
        textvariable=textvariable,
        values=values,
        width=20,
        style='TCombobox',
        font=('Segoe UI', 10),
        state='readonly'
    )
    return combobox

