"""
UI theme and styling for translation application
"""
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from typing import Dict, Tuple


def setup_theme() -> Tuple[Dict[str, str], ttk.Style]:
    """
    Setup professional modern theme for application dynamically based on appearance mode.

    Returns:
        Tuple of (colors dictionary, style object)
    """
    appearance_mode = ctk.get_appearance_mode()

    # Sleek Slate & Vibrant Cyan/Indigo theme palette
    if appearance_mode == "Dark":
        colors = {
            'navy': '#6366F1',          # Premium Indigo
            'blue': '#4F46E5',          # Dark Indigo hover
            'blue_light': '#818CF8',    # Light Indigo pressed
            'white': '#1E1E22',         # Slate Card Background
            'gray_light': '#0F0F11',    # Dark Main Background
            'gray': '#2E2E33',          # Slate border / divider
            'gray_dark': '#F3F4F6',     # High contrast off-white text
            'gray_medium': '#9CA3AF',   # Muted gray text
            'accent': '#06B6D4',        # Vibrant Cyan highlight
            'accent_hover': '#0891B2',
            'tab_selected_bg': '#6366F1',
            'tab_selected_hover': '#4F46E5'
        }
    else:
        colors = {
            'navy': '#1E3A5F',          # Deep Navy
            'blue': '#4A90E2',          # Medium Blue
            'blue_light': '#6BA3E8',    # Light Blue
            'white': '#FFFFFF',         # White Card Background
            'gray_light': '#F8F9FA',    # Light Main Background
            'gray': '#E9ECEF',          # Slate Light gray
            'gray_dark': '#1F2937',     # High contrast text
            'gray_medium': '#4B5563',   # Muted text
            'accent': '#06B6D4',        # Vibrant Cyan
            'accent_hover': '#0891B2',
            'tab_selected_bg': '#E0E7FF',
            'tab_selected_hover': '#C7D2FE'
        }

    # Create style for ttk
    style = ttk.Style()

    # Try to set theme to ensure text color displays correctly
    try:
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
                   foreground='#FFFFFF' if appearance_mode == "Dark" else colors['white'],
                   borderwidth=0,
                   focuscolor='none',
                   padding=[15, 10],
                   font=('Segoe UI', 10, 'bold'))
    style.map('Custom.TButton',
             background=[('active', colors['blue']),
                       ('pressed', colors['blue_light']),
                       ('!active', colors['navy'])],
             foreground=[('active', '#FFFFFF'),
                        ('pressed', '#FFFFFF'),
                        ('!active', '#FFFFFF')])

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

    # Premium styled Ttk Treeview configuration
    style.configure('Treeview',
                   background=colors['white'],
                   foreground=colors['gray_dark'],
                   fieldbackground=colors['white'],
                   rowheight=32,
                   borderwidth=0,
                   font=('Segoe UI', 9))
    style.configure('Treeview.Heading',
                   background=colors['gray'],
                   foreground=colors['gray_dark'],
                   font=('Segoe UI', 9, 'bold'),
                   borderwidth=0,
                   relief='flat')
    style.map('Treeview.Heading',
              background=[('active', colors['gray'])])
    style.map('Treeview',
             background=[('selected', colors['navy'])],
             foreground=[('selected', '#FFFFFF')])

    return colors, style
