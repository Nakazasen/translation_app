"""
UI theme and styling for translation application
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Tuple


def setup_theme() -> Tuple[Dict[str, str], ttk.Style]:
    """
    Setup professional theme for application
    
    Returns:
        Tuple of (colors dictionary, style object)
    """
    # Professional color palette
    colors = {
        'navy': '#1e3a5f',
        'blue': '#4a90e2',
        'blue_light': '#6ba3e8',
        'white': '#ffffff',
        'gray_light': '#f5f5f5',
        'gray': '#e0e0e0',
        'gray_dark': '#333333',
        'gray_medium': '#666666'
    }
    
    # Create style for ttk
    style = ttk.Style()
    
    # Try to set theme to ensure text color displays correctly
    try:
        # Try common themes
        available_themes = style.theme_names()
        if 'vista' in available_themes:
            style.theme_use('vista')
        elif 'clam' in available_themes:
            style.theme_use('clam')
    except Exception:
        pass
    
    # Configure style for Notebook (tabs)
    style.configure('TNotebook', background=colors['gray_light'], borderwidth=0)
    style.configure('TNotebook.Tab',
                   background=colors['gray'],
                   foreground=colors['gray_dark'],
                   padding=[20, 10],
                   font=('Segoe UI', 10, 'bold'))
    style.map('TNotebook.Tab',
             background=[('selected', colors['white'])],
             foreground=[('selected', colors['navy'])])
    
    # Configure style for Frame
    style.configure('TFrame', background=colors['gray_light'])
    
    # Configure style for Button
    style.configure('Custom.TButton',
                   background=colors['navy'],
                   foreground=colors['white'],
                   borderwidth=0,
                   focuscolor='none',
                   padding=[15, 10],
                   font=('Segoe UI', 10, 'bold'))
    style.map('Custom.TButton',
             background=[('active', colors['blue']),
                       ('pressed', colors['blue_light']),
                       ('!active', colors['navy'])],
             foreground=[('active', colors['white']),
                        ('pressed', colors['white']),
                        ('!active', colors['white'])])
    
    # Configure style for Combobox
    style.configure('TCombobox',
                   fieldbackground=colors['white'],
                   background=colors['white'],
                   foreground=colors['gray_dark'],
                   borderwidth=1,
                   relief='solid',
                   padding=5,
                   arrowcolor=colors['gray_dark'],
                   bordercolor=colors['gray'])
    style.map('TCombobox',
             fieldbackground=[('readonly', colors['white']),
                            ('!readonly', colors['white'])],
             foreground=[('readonly', colors['gray_dark']),
                       ('!readonly', colors['gray_dark'])],
             arrowcolor=[('readonly', colors['gray_dark']),
                        ('!readonly', colors['gray_dark'])],
             bordercolor=[('readonly', colors['gray']),
                        ('!readonly', colors['gray'])])
    
    # Configure style for Entry
    style.configure('TEntry',
                   fieldbackground=colors['white'],
                   borderwidth=1,
                   relief='solid',
                   padding=5)
    
    return colors, style

