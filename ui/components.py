"""
Reusable UI components for translation application using CustomTkinter
"""
import customtkinter as ctk
from typing import Callable, Optional, Dict


def create_styled_button(
    parent: ctk.CTkBaseClass,
    text: str,
    command: Optional[Callable] = None,
    colors: Optional[Dict[str, str]] = None,
    **kwargs
) -> ctk.CTkButton:
    """
    Create button with professional CustomTkinter styling

    Args:
        parent: Parent widget
        text: Button text
        command: Command to execute on click
        colors: Color dictionary (ignored in CTk as we use CTk standard themes)
        **kwargs: Additional button options

    Returns:
        Styled CTkButton widget
    """
    fg_color = kwargs.pop('fg_color', ('#4A90E2', '#6366F1'))
    hover_color = kwargs.pop('hover_color', ('#357ABD', '#4F46E5'))

    button = ctk.CTkButton(
        parent,
        text=text,
        command=command,
        font=('Segoe UI', 10, 'bold'),
        corner_radius=8,
        fg_color=fg_color,
        hover_color=hover_color,
        text_color='#FFFFFF',
        cursor='hand2',
        **kwargs
    )
    return button


def create_language_combobox(
    parent: ctk.CTkBaseClass,
    textvariable: ctk.StringVar,
    values: list,
    colors: Optional[Dict[str, str]] = None
):
    """
    Create language selection combobox using standard themed ttk.Combobox to ensure Win32 HMENU safety.
    """
    import tkinter as tk
    from tkinter import ttk

    combobox = ttk.Combobox(
        parent,
        textvariable=textvariable,
        values=values,
        width=20,
        style='TCombobox',
        font=('Segoe UI', 10),
        state='readonly'
    )
    return combobox


def create_styled_card(
    parent: ctk.CTkBaseClass,
    title: Optional[str] = None,
    accent: Optional[str] = None,
    **kwargs
) -> ctk.CTkFrame:
    """
    Create a card-like CTkFrame with premium rounded corners and thin border.

    Args:
        parent: Parent widget
        title: Optional title string to display inside at the top
        accent: Optional accent strip color name ('cyan', 'indigo', 'gold')
        **kwargs: Additional CTkFrame options

    Returns:
        ctk.CTkFrame widget
    """
    # Create the card frame with premium design tokens
    card = ctk.CTkFrame(
        parent,
        corner_radius=12,
        border_width=1,
        border_color=('#E2E8F0', '#2E2E33'),    # Modern thin borders for light/dark modes
        fg_color=('#FFFFFF', '#1E1E22'),        # Flat card backgrounds
        **kwargs
    )

    if accent:
        # Accent color lookup
        accent_colors = {
            'cyan': ('#06B6D4', '#06B6D4'),
            'indigo': ('#4A90E2', '#6366F1'),
            'gold': ('#F59E0B', '#F59E0B')
        }
        color = accent_colors.get(accent, ('#4A90E2', '#6366F1'))

        # Create a beautiful left indicator strip
        indicator = ctk.CTkFrame(
            card,
            width=4,
            height=0,
            corner_radius=2,
            fg_color=color,
            border_width=0
        )
        indicator.pack(side='left', fill='y', padx=(5, 0), pady=10)

    if title:
        # Add beautiful title inside
        title_label = ctk.CTkLabel(
            card,
            text=title,
            font=('Segoe UI', 11, 'bold'),
            text_color=('#1E3A5F', '#818CF8')   # Dynamic navy/indigo title
        )
        title_label.pack(anchor='w', padx=15, pady=(10, 5))

    return card
