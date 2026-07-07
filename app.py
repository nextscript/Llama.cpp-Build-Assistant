"""
Llama.cpp Build Assistant — Main GUI Application
Uses CustomTkinter for a modern dark-themed interface..
"""
import customtkinter as ctk
from tkinter import messagebox
import platform
import threading
import os
import json
import time
from datetime import datetime

from config import (
    ROOT_DIR, BUILD_SOURCES_FILE, BUILD_HISTORY_FILE,
    SYSTEM_REPORT_FILE, PROFILES_FILE,
    DEFAULT_BUILD_SOURCES, DEFAULT_BUILD_PROFILES,
    BUILD_TYPES, BUILD_TYPE_DISPLAY, BUILD_TYPE_FLAGS
)
from hardware_check import run_full_check, get_recommendation
from dependency_checker import check_all, get_missing_for_build_type, get_missing_programs_text
from dependency_installer import (
    has_winget, has_sudo, install_missing, check_after_install,
    get_linux_package_manager
)
from source_manager import (
    load_sources, save_sources, get_source_by_id,
    validate_source, get_default_source,
    add_source, edit_source, delete_source
)
from builder import (
    run_build, save_build_result, get_build_history,
    get_error_explanation
)
from repo_manager import ensure_repo
from profile_manager import load_profiles, add_profile, edit_profile, delete_profile
from logger import log_build, log_error, log_warning, log_install


BG = "#080d14"
SURFACE = "#101722"
SURFACE_ALT = "#121c29"
BORDER = "#273445"
TEXT = "#eef4ff"
MUTED = "#94a3b8"
BLUE = "#2563eb"
BLUE_HOVER = "#1d4ed8"
GREEN = "#7bd45a"
DANGER = "#dc2626"
DANGER_HOVER = "#b91c1c"


# ─── Main Application ───────────────────────────────────────────────

class BuildAssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Llama.cpp Build Assistant")
        self.geometry("1600x1024")
        self.minsize(1200, 800)
        self.configure(fg_color=BG)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # State
        self.hardware_report = None
        self.dep_check_results = None
        self.selected_source = ctk.StringVar(value="main")
        self.selected_build_type = ctk.StringVar(value="CPU")
        self.build_sources = load_sources()
        self.build_profiles = load_profiles()
        self.is_building = False
        self._source_name_to_id = {}

        # Build UI
        self._build_ui()

        # Auto-run hardware check on start
        self.after(500, self.run_hardware_check)

    def _card(self, parent, **kwargs):
        return ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=kwargs.pop("fg_color", SURFACE),
            border_width=1,
            border_color=BORDER,
            **kwargs
        )

    def _primary_button(self, parent, text, command=None, **kwargs):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            corner_radius=8,
            height=40,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            **kwargs
        )

    def _secondary_button(self, parent, text, command=None, **kwargs):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            corner_radius=8,
            height=40,
            fg_color=SURFACE,
            hover_color="#172235",
            border_width=1,
            border_color=BLUE,
            text_color=TEXT,
            font=ctk.CTkFont(size=13, weight="bold"),
            **kwargs
        )

    def _style_textbox(self, widget):
        widget.configure(
            fg_color="#070b11",
            border_color=BORDER,
            border_width=1,
            text_color="#c7f89a",
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569"
        )
        return widget

    def _style_field(self, widget):
        widget.configure(
            fg_color="#0b111a",
            border_color=BORDER,
            border_width=1,
            text_color=TEXT,
            placeholder_text_color=MUTED
        )
        return widget

    def _style_combo(self, widget):
        widget.configure(
            fg_color="#0b111a",
            border_color=BORDER,
            border_width=1,
            button_color=SURFACE_ALT,
            button_hover_color="#1a2a3f",
            text_color=TEXT,
            dropdown_fg_color=SURFACE,
            dropdown_hover_color=BLUE,
            dropdown_text_color=TEXT
        )
        return widget

    def _build_ui(self):
        """Build the main GUI layout."""
        # ── Top bar ──
        top_frame = ctk.CTkFrame(self, height=64, corner_radius=0, fg_color=BG)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)

        logo = ctk.CTkLabel(top_frame, text="L", width=34, height=34, corner_radius=8,
                            fg_color=BLUE, text_color="white",
                            font=ctk.CTkFont(size=18, weight="bold"))
        logo.pack(side="left", padx=(18, 12), pady=15)

        title_label = ctk.CTkLabel(top_frame, text="Llama.cpp Build Assistant",
                                   font=ctk.CTkFont(size=20, weight="bold"),
                                   text_color=TEXT)
        title_label.pack(side="left", pady=15)

        status_label = ctk.CTkLabel(top_frame, text="Ready",
                                    font=ctk.CTkFont(size=13, weight="bold"),
                                    text_color=GREEN, fg_color="#16331f",
                                    corner_radius=8, padx=16, pady=8)
        status_label.pack(side="left", padx=22, pady=15)
        self.status_label = status_label


        # ── Tabview ──
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.sidebar = self._card(body, fg_color=SURFACE_ALT, width=150)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 10), pady=0)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_propagate(False)

        self.content = self._card(body, fg_color="#0d131d")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.tab_dashboard = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_system = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_dependencies = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_build = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_history = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_sources = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_profiles = ctk.CTkFrame(self.content, fg_color="#0d131d")
        self.tab_update = ctk.CTkFrame(self.content, fg_color="#0d131d")

        self.views = {
            "Dashboard": self.tab_dashboard,
            "System Check": self.tab_system,
            "Dependencies": self.tab_dependencies,
            "Build": self.tab_build,
            "History": self.tab_history,
            "Sources": self.tab_sources,
            "Profiles": self.tab_profiles,
            "Update": self.tab_update,
        }
        self.nav_buttons = {}
        for row, name in enumerate(self.views):
            btn = ctk.CTkButton(
                self.sidebar,
                text=name,
                command=lambda n=name: self._show_view(n),
                anchor="w",
                height=48,
                corner_radius=8,
                fg_color="transparent",
                hover_color="#182438",
                text_color=TEXT,
                font=ctk.CTkFont(size=14)
            )
            btn.grid(row=row, column=0, sticky="ew", padx=8, pady=(10 if row == 0 else 5, 0))
            self.nav_buttons[name] = btn

        for frame in self.views.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._build_dashboard_tab()
        self._build_system_tab()
        self._build_dependencies_tab()
        self._build_build_tab()
        self._build_history_tab()
        self._build_sources_tab()
        self._build_profiles_tab()
        self._build_update_tab()
        self._show_view("Dashboard")

    def _show_view(self, name):
        self.views[name].tkraise()
        for item, button in self.nav_buttons.items():
            if item == name:
                button.configure(fg_color=BLUE, hover_color=BLUE_HOVER, text_color="white")
            else:
                button.configure(fg_color="transparent", hover_color="#182438", text_color=TEXT)

    # ─── Dashboard Tab ───────────────────────────────────────────────

    def _build_dashboard_tab(self):
        frame = self.tab_dashboard

        ctk.CTkLabel(frame, text="Dashboard", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        # Hardware info frame
        hw_frame = self._card(frame)
        hw_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(hw_frame, text="Hardware Overview",
                      font=ctk.CTkFont(size=15, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")

        self.lbl_cpu = ctk.CTkLabel(hw_frame, text="CPU: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_cpu.pack(padx=20, pady=3, anchor="w")
        self.lbl_ram = ctk.CTkLabel(hw_frame, text="RAM: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_ram.pack(padx=20, pady=3, anchor="w")
        self.lbl_gpu = ctk.CTkLabel(hw_frame, text="GPU: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_gpu.pack(padx=20, pady=3, anchor="w")
        self.lbl_cuda = ctk.CTkLabel(hw_frame, text="CUDA: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_cuda.pack(padx=20, pady=3, anchor="w")
        self.lbl_sycl = ctk.CTkLabel(hw_frame, text="SYCL: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_sycl.pack(padx=20, pady=3, anchor="w")
        self.lbl_os = ctk.CTkLabel(hw_frame, text="OS: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_os.pack(padx=20, pady=3, anchor="w")
        self.lbl_disk = ctk.CTkLabel(hw_frame, text="Free Disk: Loading...", font=ctk.CTkFont(size=13))
        self.lbl_disk.pack(padx=20, pady=3, anchor="w")

        # Recommendation
        rec_frame = self._card(frame)
        rec_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(rec_frame, text="Recommended Build",
                      font=ctk.CTkFont(size=15, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")
        self.lbl_recommendation = ctk.CTkLabel(rec_frame, text="Running hardware check...",
                                                font=ctk.CTkFont(size=14, weight="bold"),
                                                text_color=("blue", "cyan"))
        self.lbl_recommendation.pack(padx=20, pady=(5, 15), anchor="w")

        # Current source
        src_frame = self._card(frame)
        src_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(src_frame, text="Selected Source",
                      font=ctk.CTkFont(size=15, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")
        self.lbl_current_source = ctk.CTkLabel(src_frame, text="main llama.cpp",
                                                font=ctk.CTkFont(size=14))
        self.lbl_current_source.pack(padx=20, pady=(5, 15), anchor="w")

    # ─── System Check Tab ────────────────────────────────────────────

    def _build_system_tab(self):
        frame = self.tab_system

        ctk.CTkLabel(frame, text="System Check", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkButton(btn_frame, text="Run System Check",
                       command=self.run_hardware_check,
                       corner_radius=8, height=36).pack(
            side="left", padx=15, pady=15)

        ctk.CTkButton(btn_frame, text="Export Report",
                       command=self.export_system_report,
                       corner_radius=8, height=36,
                       fg_color=SURFACE_ALT, hover_color="#172235").pack(
            side="left", padx=10, pady=15)

        # Results
        self.sys_text = self._style_textbox(ctk.CTkTextbox(frame, height=400, font=ctk.CTkFont(size=12),
                                                           corner_radius=8))
        self.sys_text.pack(fill="both", expand=True, padx=25, pady=10)

    # ─── Dependencies Tab ────────────────────────────────────────────

    def _build_dependencies_tab(self):
        frame = self.tab_dependencies

        ctk.CTkLabel(frame, text="Dependencies", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkButton(btn_frame, text="Check Dependencies",
                       command=self.check_dependencies,
                       corner_radius=8, height=36).pack(
            side="left", padx=15, pady=15)

        ctk.CTkButton(btn_frame, text="Install Missing",
                       command=self.install_missing_deps,
                       corner_radius=8, height=36,
                       fg_color=BLUE, hover_color=BLUE_HOVER).pack(
            side="left", padx=10, pady=15)

        ctk.CTkButton(btn_frame, text="Show Manual Guide",
                       command=self.show_manual_guide,
                       corner_radius=8, height=36,
                       fg_color=SURFACE_ALT, hover_color="#172235").pack(
            side="left", padx=10, pady=15)

        # Results
        self.dep_text = self._style_textbox(ctk.CTkTextbox(frame, height=400, font=ctk.CTkFont(size=12),
                                                           corner_radius=8))
        self.dep_text.pack(fill="both", expand=True, padx=25, pady=10)

    # ─── Build Tab ───────────────────────────────────────────────────

    def _build_build_tab(self):
        frame = self.tab_build
        frame.grid_columnconfigure(0, weight=3)
        frame.grid_columnconfigure(1, weight=2)
        frame.grid_rowconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(frame, corner_radius=0, fg_color="#0d131d")
        scroll_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)

        log_frame = self._card(frame, width=420)
        log_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_propagate(False)

        ctk.CTkLabel(scroll_frame, text="Build Configuration", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        src_frame = self._card(scroll_frame)
        src_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(src_frame, text="Build Source:",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")

        self.source_combo = self._style_combo(ctk.CTkComboBox(src_frame, values=[],
                                                              variable=self.selected_source,
                                                              command=self.on_source_changed,
                                                              corner_radius=8, height=36))
        self.source_combo.pack(padx=20, pady=(5, 15), fill="x")
        self._update_source_combo()

        bt_frame = self._card(scroll_frame)
        bt_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(bt_frame, text="Build Type:",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")

        self.build_type_combo = self._style_combo(ctk.CTkComboBox(bt_frame, values=BUILD_TYPES,
                                                                  variable=self.selected_build_type,
                                                                  corner_radius=8, height=36))
        self.build_type_combo.pack(padx=20, pady=(5, 15), fill="x")

        opt_frame = self._card(scroll_frame)
        opt_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(opt_frame, text="Build Options:",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")

        self.clean_build_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt_frame, text="Clean Build",
                         variable=self.clean_build_var,
                         font=ctk.CTkFont(size=13)).pack(
            padx=20, pady=4, anchor="w")

        self.update_repo_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt_frame, text="Update repository before build",
                         variable=self.update_repo_var,
                         font=ctk.CTkFont(size=13)).pack(
            padx=20, pady=4, anchor="w")

        self.build_ui_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt_frame, text="Build web UI (needs npm)",
                         variable=self.build_ui_var,
                         font=ctk.CTkFont(size=13)).pack(
            padx=20, pady=(4, 15), anchor="w")

        cmake_frame = self._card(scroll_frame)
        cmake_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(cmake_frame, text="Custom CMake Flags (optional):",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")
        self.cmake_flags_entry = self._style_field(ctk.CTkEntry(cmake_frame, placeholder_text="-DGGML_NATIVE=ON",
                                                                corner_radius=8, height=36))
        self.cmake_flags_entry.pack(padx=20, pady=(5, 15), fill="x")

        self.custom_frame = self._card(scroll_frame)
        self.custom_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(self.custom_frame, text="Custom Repository URL:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.custom_url_entry = self._style_field(ctk.CTkEntry(self.custom_frame,
                                                               placeholder_text="https://github.com/user/repo",
                                                               corner_radius=8, height=36))
        self.custom_url_entry.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(self.custom_frame, text="Branch:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.custom_branch_entry = self._style_field(ctk.CTkEntry(self.custom_frame,
                                                                  placeholder_text="master",
                                                                  corner_radius=8, height=36))
        self.custom_branch_entry.pack(padx=20, pady=(5, 15), fill="x")

        btn_frame = self._card(scroll_frame)
        btn_frame.pack(fill="x", padx=25, pady=15)

        self.build_btn = ctk.CTkButton(btn_frame, text="Start Build",
                                        font=ctk.CTkFont(size=18, weight="bold"),
                                        fg_color=BLUE,
                                        hover_color=BLUE_HOVER,
                                        corner_radius=10, height=50,
                                        command=self.start_build)
        self.build_btn.pack(padx=25, pady=20, fill="x")

        ctk.CTkLabel(log_frame, text="Live Build Log:",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")

        self.build_log_text = self._style_textbox(ctk.CTkTextbox(log_frame, font=ctk.CTkFont(size=11),
                                                                 corner_radius=8))
        self.build_log_text.pack(fill="both", expand=True, padx=20, pady=(5, 15))

    # ─── History Tab ─────────────────────────────────────────────────

    def _build_history_tab(self):
        frame = self.tab_history

        ctk.CTkLabel(frame, text="Build History", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        ctk.CTkButton(frame, text="Refresh History",
                       command=self.load_build_history,
                       corner_radius=8, height=36,
                       fg_color=SURFACE_ALT, hover_color="#172235").pack(
            padx=25, pady=8, anchor="w")

        self.history_text = self._style_textbox(ctk.CTkTextbox(frame, height=450, font=ctk.CTkFont(size=12),
                                                               corner_radius=8))
        self.history_text.pack(fill="both", expand=True, padx=25, pady=10)

        self.load_build_history()

    # ─── Sources Tab ─────────────────────────────────────────────────

    def _build_sources_tab(self):
        frame = self.tab_sources

        ctk.CTkLabel(frame, text="Build Sources Management",
                      font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        # List
        self.sources_listbox = self._style_textbox(ctk.CTkTextbox(frame, height=250, font=ctk.CTkFont(size=12),
                                                                  corner_radius=8))
        self.sources_listbox.pack(fill="both", expand=True, padx=25, pady=8)
        self._update_sources_list()

        # Buttons
        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkButton(btn_frame, text="Add Source",
                       command=self.add_source_dialog,
                       corner_radius=8, height=36,
                       fg_color=BLUE, hover_color=BLUE_HOVER).pack(
            side="left", padx=10, pady=15)
        ctk.CTkButton(btn_frame, text="Edit Source",
                       command=self.edit_selected_source,
                       corner_radius=8, height=36).pack(
            side="left", padx=10, pady=15)
        ctk.CTkButton(btn_frame, text="Delete Source",
                       command=self.delete_selected_source,
                       corner_radius=8, height=36,
                       fg_color=DANGER, hover_color=DANGER_HOVER).pack(
            side="left", padx=10, pady=15)

        # Edit form
        edit_frame = self._card(frame)
        edit_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(edit_frame, text="Selected Source ID:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_source_id = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="main",
                                                             corner_radius=8, height=36))
        self.edit_source_id.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(edit_frame, text="Name:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_name = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="my fork",
                                                        corner_radius=8, height=36))
        self.edit_name.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(edit_frame, text="Repo URL:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_url = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="https://github.com/...",
                                                       corner_radius=8, height=36))
        self.edit_url.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(edit_frame, text="Branch:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_branch = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="master",
                                                          corner_radius=8, height=36))
        self.edit_branch.pack(padx=20, pady=(5, 15), fill="x")

    # ─── Profiles Tab ────────────────────────────────────────────────

    def _build_profiles_tab(self):
        frame = self.tab_profiles

        ctk.CTkLabel(frame, text="Build Profiles", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        self.profiles_listbox = self._style_textbox(ctk.CTkTextbox(frame, height=250, font=ctk.CTkFont(size=12),
                                                                   corner_radius=8))
        self.profiles_listbox.pack(fill="both", expand=True, padx=25, pady=8)
        self._update_profiles_list()

        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkButton(btn_frame, text="Add Profile",
                       command=self.add_profile_dialog,
                       corner_radius=8, height=36,
                       fg_color=BLUE, hover_color=BLUE_HOVER).pack(
            side="left", padx=10, pady=15)
        ctk.CTkButton(btn_frame, text="Delete Profile",
                       command=self.delete_selected_profile,
                       corner_radius=8, height=36,
                       fg_color=DANGER, hover_color=DANGER_HOVER).pack(
            side="left", padx=10, pady=15)
        ctk.CTkButton(btn_frame, text="Apply Profile",
                       command=self.apply_profile,
                       corner_radius=8, height=36).pack(
            side="left", padx=10, pady=15)

        edit_frame = self._card(frame)
        edit_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(edit_frame, text="Profile Name:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_profile_name = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="My Profile",
                                                                corner_radius=8, height=36))
        self.edit_profile_name.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(edit_frame, text="Source ID:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_profile_source = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="main",
                                                                  corner_radius=8, height=36))
        self.edit_profile_source.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(edit_frame, text="Build Type:",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_profile_type = self._style_combo(ctk.CTkComboBox(edit_frame, values=BUILD_TYPES,
                                                                   corner_radius=8, height=36))
        self.edit_profile_type.pack(padx=20, pady=5, fill="x")
        ctk.CTkLabel(edit_frame, text="CMake Flags (comma-separated):",
                      font=ctk.CTkFont(size=13)).pack(padx=20, pady=(10, 5), anchor="w")
        self.edit_profile_flags = self._style_field(ctk.CTkEntry(edit_frame, placeholder_text="-DGGML_CUDA=ON",
                                                                 corner_radius=8, height=36))
        self.edit_profile_flags.pack(padx=20, pady=(5, 15), fill="x")

    # ─── Update Tab ──────────────────────────────────────────────────

    def _build_update_tab(self):
        frame = self.tab_update

        ctk.CTkLabel(frame, text="Application Update", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        info_frame = self._card(frame)
        info_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(info_frame, text="Current Version:",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 5), anchor="w")

        version = self._get_local_version()
        self.lbl_app_version = ctk.CTkLabel(info_frame, text=f"v{version}",
                                             font=ctk.CTkFont(size=16, weight="bold"),
                                             text_color=GREEN)
        self.lbl_app_version.pack(padx=20, pady=(0, 5), anchor="w")

        ctk.CTkLabel(info_frame, text="Repository: nextscript/Llama.cpp-Build-Assistant",
                      font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            padx=20, pady=(0, 15), anchor="w")

        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        self.update_btn = ctk.CTkButton(btn_frame, text="Check for Updates",
                                         command=self.check_for_updates,
                                         corner_radius=8, height=42,
                                         fg_color=BLUE, hover_color=BLUE_HOVER,
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.update_btn.pack(side="left", padx=15, pady=15)

        self.update_status_lbl = ctk.CTkLabel(btn_frame, text="",
                                               font=ctk.CTkFont(size=13),
                                               text_color=MUTED)
        self.update_status_lbl.pack(side="left", padx=10, pady=15)

    # ─── Hardware Check ──────────────────────────────────────────────

    def run_hardware_check(self):
        """Run hardware check in a background thread."""
        self.status_label.configure(text="Checking hardware...")

        def _check():
            try:
                report = run_full_check()
                self.hardware_report = report
                self.dep_check_results = check_all()

                # Update dashboard
                cpu = report.get("cpu", {})
                ram = report.get("ram", {})
                gpu = report.get("gpu", {})

                self.lbl_cpu.configure(text=f"CPU: {cpu.get('name', 'Unknown')} "
                                            f"({cpu.get('cores', 0)} cores, {cpu.get('threads', 0)} threads)")
                self.lbl_ram.configure(text=f"RAM: {ram.get('total_gb', 0)} GB total, "
                                            f"{ram.get('free_gb', 0)} GB free")

                gpus = gpu.get("gpus", [])
                if gpus:
                    gpu_names = ", ".join(g.get("name", "Unknown") for g in gpus)
                    self.lbl_gpu.configure(text=f"GPU: {gpu_names}")
                else:
                    self.lbl_gpu.configure(text="GPU: None detected")

                self.lbl_cuda.configure(text=f"CUDA: {'Available ' + gpu.get('cuda_version', '') if gpu.get('cuda_available') else 'Not available'}")
                self.lbl_sycl.configure(text=f"SYCL: {'Available' if gpu.get('sycl_available') else 'Not available'}")
                self.lbl_os.configure(text=f"OS: {report.get('os', 'Unknown')}")
                self.lbl_disk.configure(text=f"Free Disk: {report.get('free_disk_gb', 0)} GB")

                # Recommendation
                rec = get_recommendation(report)
                self.selected_build_type.set(rec)
                self.lbl_recommendation.configure(
                    text=f"Recommended: {BUILD_TYPE_DISPLAY.get(rec, rec)} Build "
                         f"({BUILD_TYPE_FLAGS.get(rec, '')})")

                # Update system tab
                self._update_system_tab(report)

                # Update status
                self.status_label.configure(text="Hardware check complete")

            except Exception as e:
                log_error(f"Hardware check failed: {e}")
                self.status_label.configure(text="Hardware check failed")

        threading.Thread(target=_check, daemon=True).start()

    def _update_system_tab(self, report):
        """Update the System Check tab with report data."""
        lines = []
        lines.append("=" * 60)
        lines.append("SYSTEM CHECK REPORT")
        lines.append("=" * 60)
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        lines.append("Operating System:")
        lines.append(f"  {report.get('os', 'Unknown')}")
        lines.append("")

        cpu = report.get("cpu", {})
        lines.append("CPU:")
        lines.append(f"  Model: {cpu.get('name', 'Unknown')}")
        lines.append(f"  Cores: {cpu.get('cores', 0)}")
        lines.append(f"  Threads: {cpu.get('threads', 0)}")
        lines.append(f"  Features: {', '.join(cpu.get('features', [])) or 'None detected'}")
        lines.append("")

        ram = report.get("ram", {})
        lines.append("RAM:")
        lines.append(f"  Total: {ram.get('total_gb', 0)} GB")
        lines.append(f"  Free: {ram.get('free_gb', 0)} GB")
        lines.append("")

        gpu = report.get("gpu", {})
        lines.append("GPU:")
        gpus = gpu.get("gpus", [])
        if gpus:
            for g in gpus:
                lines.append(f"  {g.get('name', 'Unknown')} ({g.get('vendor', 'Unknown')}, "
                             f"{g.get('vram_gb', 0)} GB VRAM)")
        else:
            lines.append("  None detected")
        lines.append("")

        lines.append("GPU Features:")
        lines.append(f"  NVIDIA: {'Yes' if gpu.get('has_nvidia') else 'No'}")
        if gpu.get('nvidia_driver_version'):
            lines.append(f"  Driver Version: {gpu['nvidia_driver_version']}")
        lines.append(f"  CUDA: {'Available' if gpu.get('cuda_available') else 'Not available'}")
        if gpu.get('cuda_version'):
            lines.append(f"  CUDA Version: {gpu['cuda_version']}")
        lines.append(f"  Vulkan: {'Available' if gpu.get('vulkan_available') else 'Not available'}")
        lines.append(f"  ROCm/HIP: {'Available' if gpu.get('rocm_available') else 'Not available'}")
        lines.append(f"  SYCL (Intel): {'Available' if gpu.get('sycl_available') else 'Not available'}")
        lines.append("")

        lines.append(f"Free Disk Space: {report.get('free_disk_gb', 0)} GB")
        lines.append("")

        rec = get_recommendation(report)
        lines.append(f"Recommended Build: {BUILD_TYPE_DISPLAY.get(rec, rec)} "
                      f"({BUILD_TYPE_FLAGS.get(rec, '')})")

        self.sys_text.delete("1.0", "end")
        self.sys_text.insert("1.0", "\n".join(lines))

    # ─── Dependencies ────────────────────────────────────────────────

    def check_dependencies(self):
        """Check all dependencies and display results."""
        results = check_all()
        lines = []
        lines.append("=" * 60)
        lines.append("DEPENDENCY CHECK")
        lines.append("=" * 60)
        lines.append("")

        for name, info in results.items():
            status = "FOUND" if info.get("found") else "MISSING"
            version = info.get("version", "") or info.get("path", "")
            lines.append(f"  {name:20s} [{status:7s}] {version}")

        lines.append("")

        # Check missing for current selection
        src_name = self.selected_source.get()
        src_id = self._source_name_to_id.get(src_name, src_name)
        bt = self.selected_build_type.get()
        missing = get_missing_for_build_type(results, bt)
        missing_names = get_missing_programs_text(missing)

        if missing_names:
            lines.append(f"Missing for {bt} build: {', '.join(missing_names)}")
        else:
            lines.append(f"All dependencies for {bt} build are satisfied!")

        self.dep_text.delete("1.0", "end")
        self.dep_text.insert("1.0", "\n".join(lines))

    def install_missing_deps(self):
        """Show install dialog for missing dependencies."""
        if not self.dep_check_results:
            self.dep_check_results = check_all()

        bt = self.selected_build_type.get()
        missing = get_missing_for_build_type(self.dep_check_results, bt)
        missing_names = get_missing_programs_text(missing)

        if not missing:
            messagebox.showinfo("Dependencies", "All dependencies are already installed!")
            return

        # Check platform support
        system = platform.system()
        if system == "Windows" and not has_winget():
            messagebox.showerror("Installation Not Available",
                          "winget was not found.\n"
                          "Automatic installation is not available on this system.\n\n"
                          "Please install the missing programs manually:\n" +
                          "\n".join(f"- {n}" for n in missing_names))
            return

        # CUDA special warning
        if "cuda_toolkit" in missing:
            result = messagebox.askyesno(
                "CUDA Installation Warning",
                "CUDA Toolkit is missing.\n\n"
                "WARNING:\n"
                "Automatic CUDA installation may require a system restart.\n"
                "Also, the CUDA version must match your NVIDIA driver.\n\n"
                "Do you want to install CUDA automatically?")
            if not result:
                return

        # Show confirmation
        result = messagebox.askyesno(
            "Install Missing Dependencies",
            f"The following programs are missing:\n\n" +
            "\n".join(f"- {n}" for n in missing_names) +
            "\n\nShould these programs be installed automatically?")

        if not result:
            return

        # Show install dialog with live output
        install_win = ctk.CTkToplevel(self)
        install_win.title("Installing Dependencies")
        install_win.geometry("600x400")

        ctk.CTkLabel(install_win, text="Installing dependencies...",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(15, 5))

        install_log = ctk.CTkTextbox(install_win, height=250, font=ctk.CTkFont(size=10))
        install_log.pack(fill="both", expand=True, padx=15, pady=5)

        def install_callback(line):
            install_log.insert("end", line + "\n")
            install_log.see("end")

        def do_install():
            results = install_missing(missing, callback=install_callback)
            all_ok = all(v[0] for v in results.values())

            install_log.insert("end", "\n" + "=" * 40 + "\n")
            if all_ok:
                install_log.insert("end", "All installations completed successfully!\n")
                install_log.insert("end", "Re-checking dependencies...\n")

                # Re-check
                new_results = check_after_install()
                for name, info in new_results.items():
                    status = "OK" if info.get("found") else "STILL MISSING"
                    install_log.insert("end", f"  {name}: {status}\n")

                self.dep_check_results = new_results
                self.after(0, self.check_dependencies)
            else:
                install_log.insert("end", "Some installations failed.\n")
                for dep, (success, msg) in results.items():
                    if not success:
                        install_log.insert("end", f"  {dep}: {msg}\n")

            install_log.see("end")

        threading.Thread(target=do_install, daemon=True).start()

    def show_manual_guide(self):
        """Show manual installation guide."""
        system = platform.system()
        guide = ""

        if system == "Windows":
            guide = """
MANUAL INSTALLATION GUIDE (Windows)
====================================

Install the following programs manually:

1. Git:
   Download from: https://git-scm.com/download/win
   Or: winget install --id Git.Git -e --source winget

2. CMake:
   Download from: https://cmake.org/download/
   Or: winget install --id Kitware.CMake -e --source winget

3. Visual Studio Build Tools 2022:
   Download from: https://visualstudio.microsoft.com/downloads/
   Select "Desktop development with C++" workload
   Or: winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget

4. Ninja:
   Download from: https://github.com/ninja-build/ninja/releases
   Or: winget install --id Ninja-build.Ninja -e --source winget

5. CUDA Toolkit (for CUDA builds):
   Download from: https://developer.nvidia.com/cuda-downloads

6. Vulkan SDK (for Vulkan builds):
   Download from: https://vulkan.lunarg.com/sdk/home

7. Intel oneAPI Base Toolkit (for SYCL/Intel GPU builds):
   Download from: https://www.intel.com/content/www/us/en/developer/tools/oneapi/base-toolkit-download.html
   Or: winget install Intel.oneAPI.BaseToolkit
"""
        elif system == "Linux":
            pm = get_linux_package_manager()
            if pm == "apt":
                guide = """
MANUAL INSTALLATION GUIDE (Debian/Ubuntu)
==========================================

Run:
  sudo apt update
  sudo apt install -y git cmake build-essential ninja-build

For CUDA:
  Visit: https://developer.nvidia.com/cuda-downloads

For Vulkan SDK:
  sudo apt install -y vulkan-sdk
"""
            elif pm == "dnf":
                guide = """
MANUAL INSTALLATION GUIDE (Fedora)
===================================

Run:
  sudo dnf install -y git cmake gcc gcc-c++ make ninja-build

For CUDA and Vulkan, visit the respective download pages.
"""
            elif pm == "pacman":
                guide = """
MANUAL INSTALLATION GUIDE (Arch Linux)
=======================================

Run:
  sudo pacman -Syu --needed git cmake base-devel ninja

For CUDA and Vulkan, visit the respective download pages.
"""
            else:
                guide = """
MANUAL INSTALLATION GUIDE (Linux)
==================================

Install using your package manager:
  git, cmake, gcc/g++, make, ninja-build

For CUDA: https://developer.nvidia.com/cuda-downloads
For Vulkan: https://vulkan.lunarg.com/sdk/home
"""
        else:
            guide = "Please install Git, CMake, a C/C++ compiler, and Ninja manually."

        messagebox.showinfo("Manual Installation Guide", guide.strip())

    # ─── Build ───────────────────────────────────────────────────────

    def on_source_changed(self, source_name):
        source_id = self._source_name_to_id.get(source_name, source_name)
        source = get_source_by_id(source_id)
        if not source:
            return

        # Update custom fields
        if source_id == "custom" or (source.get("repo_url") == "" and source.get("type") == "custom"):
            self.custom_frame.pack(fill="x", padx=20, pady=5)
            self.custom_url_entry.configure(state="normal")
            self.custom_branch_entry.configure(state="normal")
            if source.get("repo_url"):
                self.custom_url_entry.delete(0, "end")
                self.custom_url_entry.insert(0, source["repo_url"])
            if source.get("branch"):
                self.custom_branch_entry.delete(0, "end")
                self.custom_branch_entry.insert(0, source["branch"])
        else:
            self.custom_frame.pack_forget()

        # Update source label on dashboard
        self.lbl_current_source.configure(text=source.get("name", source_id))

    def start_build(self):
        source_name = self.selected_source.get()
        source_id = self._source_name_to_id.get(source_name, source_name)
        source = get_source_by_id(source_id)

        if not source:
            messagebox.showerror("Error", f"Source '{source_id}' not found.")
            return

        # Check URL
        if not source.get("repo_url"):
            if source_id == "custom":
                url = self.custom_url_entry.get().strip()
                if not url:
                    messagebox.showerror("Error",
                                  "No repository URL configured.\n"
                                  "Please enter a valid Git URL.")
                    return
                source["repo_url"] = url
            else:
                messagebox.showerror("Error",
                              "No repository URL configured for this build source.\n"
                              "Please configure a valid Git URL first.")
                return

        # Check dependencies
        if not self.dep_check_results:
            self.dep_check_results = check_all()

        bt = self.selected_build_type.get()
        missing = get_missing_for_build_type(self.dep_check_results, bt)
        if missing:
            missing_names = get_missing_programs_text(missing)
            messagebox.showerror("Missing Dependencies",
                          f"The following required programs are missing:\n\n" +
                          "\n".join(f"- {n}" for n in missing_names) +
                          "\n\nPlease install them via the Dependencies tab before building.")
            return

        # Clear log
        self.build_log_text.delete("1.0", "end")

        self.is_building = True
        self.build_btn.configure(state="disabled", text="Building...")
        self.status_label.configure(text="Building...")

        # Get custom flags
        custom_flags_str = self.cmake_flags_entry.get().strip()
        custom_flags = [f.strip() for f in custom_flags_str.split(",") if f.strip()] if custom_flags_str else []

        def do_build():
            try:
                start_time = time.time()

                def callback(line):
                    self.build_log_text.insert("end", line + "\n")
                    self.build_log_text.see("end")

                success, output, error_msg, binaries = run_build(
                    source_id, bt,
                    update_repo_flag=self.update_repo_var.get(),
                    custom_flags=custom_flags,
                    clean_build=self.clean_build_var.get(),
                    callback=callback,
                    build_ui=self.build_ui_var.get()
                )

                duration = time.time() - start_time

                # Save result
                build_path = os.path.join(ROOT_DIR, "builds",
                                          f"{source_id.replace('_', '-')}-{bt.lower()}")
                save_build_result(source_id, bt, success, build_path,
                                  binaries, duration, error_msg)

                if success:
                    self.build_log_text.insert("end", "\n" + "=" * 60 + "\n")
                    self.build_log_text.insert("end", "BUILD SUCCESSFUL!\n")
                    self.build_log_text.insert("end", f"Duration: {duration:.1f} seconds\n")
                    if binaries:
                        self.build_log_text.insert("end", f"Binaries: {len(binaries)} found\n")
                        for b in binaries[:10]:
                            self.build_log_text.insert("end", f"  {b}\n")
                    self.status_label.configure(text="Build successful!")
                else:
                    self.build_log_text.insert("end", "\n" + "=" * 60 + "\n")
                    self.build_log_text.insert("end", "BUILD FAILED!\n")
                    self.build_log_text.insert("end", f"Error: {error_msg}\n")

                    # Show explanation
                    explanation = get_error_explanation(error_msg)
                    self.build_log_text.insert("end", f"\nCause: {explanation['cause']}\n")
                    self.build_log_text.insert("end", f"Solution: {explanation['solution']}\n")
                    self.build_log_text.insert("end", f"Fallback: {explanation['fallback']}\n")

                    self.status_label.configure(text="Build failed")

            except Exception as e:
                self.build_log_text.insert("end", f"\nUnexpected error: {e}\n")
                log_error(f"Build error: {e}")
                self.status_label.configure(text="Build error")

            self.is_building = False
            self.after(0, lambda: self.build_btn.configure(state="normal", text="Start Build"))

        threading.Thread(target=do_build, daemon=True).start()

    # ─── History ─────────────────────────────────────────────────────

    def load_build_history(self):
        """Load and display build history."""
        history = get_build_history()
        lines = []
        lines.append("=" * 60)
        lines.append("BUILD HISTORY")
        lines.append("=" * 60)
        lines.append("")

        if not history:
            lines.append("No builds recorded yet.")
        else:
            for entry in reversed(history):
                lines.append(f"Date: {entry.get('date', 'N/A')}")
                lines.append(f"  Source: {entry.get('source_name', 'N/A')}")
                lines.append(f"  Type: {entry.get('build_type', 'N/A')}")
                lines.append(f"  Success: {entry.get('success', False)}")
                lines.append(f"  Path: {entry.get('build_path', 'N/A')}")
                if entry.get('duration_seconds'):
                    lines.append(f"  Duration: {entry['duration_seconds']:.1f}s")
                if entry.get('error_message'):
                    lines.append(f"  Error: {entry['error_message'][:100]}")
                lines.append("")

        self.history_text.delete("1.0", "end")
        self.history_text.insert("1.0", "\n".join(lines))

    # ─── Sources Management ──────────────────────────────────────────

    def _update_sources_list(self):
        """Update the sources listbox."""
        sources = load_sources()
        lines = []
        for s in sources:
            exp = "EXPERIMENTAL" if s.get("experimental") else ""
            lines.append(f"  [{s['id']}] {s['name']} ({s.get('type', 'unknown')}) {exp}")
            if s.get("repo_url"):
                lines.append(f"    URL: {s['repo_url']}")
                lines.append(f"    Branch: {s.get('branch', 'N/A')}")
            lines.append("")
        self.sources_listbox.delete("1.0", "end")
        self.sources_listbox.insert("1.0", "\n".join(lines))

    def add_source_dialog(self):
        """Show dialog to add a new source."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Build Source")
        dialog.geometry("500x350")

        ctk.CTkLabel(dialog, text="Add Build Source",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(15, 5))

        fields = [
            ("Name:", "name", "my-fork"),
            ("Repo URL:", "url", "https://github.com/user/repo"),
            ("Branch:", "branch", "master"),
            ("Local Path:", "path", "repos/my-fork"),
        ]

        entries = {}
        for label, key, placeholder in fields:
            ctk.CTkLabel(dialog, text=label).pack(pady=(5, 0), padx=20, anchor="w")
            entry = ctk.CTkEntry(dialog, placeholder_text=placeholder)
            entry.pack(pady=2, padx=20, fill="x")
            entries[key] = entry

        exp_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(dialog, text="Mark as experimental",
                         variable=exp_var).pack(pady=5, padx=20, anchor="w")

        def add():
            name = entries["name"].get().strip()
            url = entries["url"].get().strip()
            branch = entries["branch"].get().strip()
            path = entries["path"].get().strip()
            exp = exp_var.get()

            if not name or not url:
                messagebox.showerror("Error", "Name and Repo URL are required.")
                return

            ok, msg = add_source(name, url, branch, path,
                                 source_type="custom", experimental=exp)
            if ok:
                self.build_sources = load_sources()
                self._update_sources_list()
                self._update_source_combo()
                dialog.destroy()
            else:
                messagebox.showerror("Error", msg)

        ctk.CTkButton(dialog, text="Add", command=add).pack(pady=15)

    def edit_selected_source(self):
        """Edit the selected source."""
        source_id = self.edit_source_id.get().strip()
        if not source_id:
            messagebox.showerror("Error", "Please enter a source ID.")
            return

        name = self.edit_name.get().strip()
        url = self.edit_url.get().strip()
        branch = self.edit_branch.get().strip()

        kwargs = {}
        if name:
            kwargs["name"] = name
        if url:
            kwargs["repo_url"] = url
        if branch:
            kwargs["branch"] = branch

        ok, msg = edit_source(source_id, **kwargs)
        if ok:
            self.build_sources = load_sources()
            self._update_sources_list()
            self._update_source_combo()
        else:
            messagebox.showerror("Error", msg)

    def delete_selected_source(self):
        """Delete the selected source."""
        source_id = self.edit_source_id.get().strip()
        if not source_id:
            messagebox.showerror("Error", "Please enter a source ID.")
            return

        if source_id == "main":
            messagebox.showerror("Error", "Cannot delete the main source.")
            return

        result = messagebox.askyesno("Confirm Delete",
                                  f"Delete source '{source_id}'?")
        if not result:
            return

        ok, msg = delete_source(source_id)
        if ok:
            self.build_sources = load_sources()
            self._update_sources_list()
            self._update_source_combo()
        else:
            messagebox.showerror("Error", msg)

    def _update_source_combo(self):
        sources = load_sources()
        self._source_name_to_id = {}
        names = []
        for s in sources:
            name = s.get("name", s.get("id", ""))
            sid = s.get("id", "")
            self._source_name_to_id[name] = sid
            names.append(name)
        self.source_combo.configure(values=names)
        default_name = None
        for s in sources:
            if s.get("id") == "main":
                default_name = s.get("name", "main")
                break
        if default_name:
            self.selected_source.set(default_name)
        elif names:
            self.selected_source.set(names[0])

    # ─── Profiles Management ─────────────────────────────────────────

    def _update_profiles_list(self):
        """Update the profiles listbox."""
        profiles = load_profiles()
        lines = []
        for p in profiles:
            exp = "EXPERIMENTAL" if p.get("experimental") else ""
            lines.append(f"  [{p['name']}] source={p['source']}, type={p['build_type']} {exp}")
            lines.append(f"    Flags: {', '.join(p.get('cmake_flags', []))}")
            lines.append("")
        self.profiles_listbox.delete("1.0", "end")
        self.profiles_listbox.insert("1.0", "\n".join(lines))

    def add_profile_dialog(self):
        """Show dialog to add a profile."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Build Profile")
        dialog.geometry("500x300")

        ctk.CTkLabel(dialog, text="Add Build Profile",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(15, 5))

        fields = [
            ("Name:", "name", "My Profile"),
            ("Source ID:", "source", "main"),
            ("Build Type:", "type", "CPU"),
            ("CMake Flags:", "flags", "-DGGML_NATIVE=ON"),
        ]

        entries = {}
        for label, key, placeholder in fields:
            ctk.CTkLabel(dialog, text=label).pack(pady=(5, 0), padx=20, anchor="w")
            if key == "type":
                entry = ctk.CTkComboBox(dialog, values=BUILD_TYPES)
            else:
                entry = ctk.CTkEntry(dialog, placeholder_text=placeholder)
            entry.pack(pady=2, padx=20, fill="x")
            entries[key] = entry

        def add():
            name = entries["name"].get().strip()
            source = entries["source"].get().strip()
            build_type = entries["type"].get()
            flags_str = entries["flags"].get().strip()
            flags = [f.strip() for f in flags_str.split(",") if f.strip()] if flags_str else []

            if not name or not source:
                messagebox.showerror("Error", "Name and Source are required.")
                return

            ok, msg = add_profile(name, source, build_type, flags)
            if ok:
                self.build_profiles = load_profiles()
                self._update_profiles_list()
                dialog.destroy()
            else:
                messagebox.showerror("Error", msg)

        ctk.CTkButton(dialog, text="Add", command=add).pack(pady=15)

    def delete_selected_profile(self):
        """Delete the selected profile."""
        name = self.edit_profile_name.get().strip()
        if not name:
            messagebox.showerror("Error", "Please enter a profile name.")
            return

        result = messagebox.askyesno("Confirm Delete", f"Delete profile '{name}'?")
        if not result:
            return

        ok, msg = delete_profile(name)
        if ok:
            self.build_profiles = load_profiles()
            self._update_profiles_list()
        else:
            messagebox.showerror("Error", msg)

    def apply_profile(self):
        """Apply a build profile to the current settings."""
        name = self.edit_profile_name.get().strip()
        profile = None
        for p in load_profiles():
            if p.get("name") == name:
                profile = p
                break

        if not profile:
            messagebox.showerror("Error", f"Profile '{name}' not found.")
            return

        profile_source_id = profile.get("source", "main")
        source_name = profile_source_id
        for sname, sid in self._source_name_to_id.items():
            if sid == profile_source_id:
                source_name = sname
                break
        self.selected_source.set(source_name)
        self.selected_build_type.set(profile.get("build_type", "CPU"))

        flags = profile.get("cmake_flags", [])
        self.cmake_flags_entry.delete(0, "end")
        if flags:
            self.cmake_flags_entry.insert(0, ", ".join(flags))

        self.clean_build_var.set(profile.get("clean_build", True))
        self.update_repo_var.set(profile.get("update_repo", True))

        self.on_source_changed(source_name)

    def export_system_report(self):
        """Export the system report as JSON."""
        if not self.hardware_report:
            messagebox.showinfo("Export", "No hardware report available. Run a system check first.")
            return

        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile=f"system_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        if path:
            try:
                with open(path, "w") as f:
                    json.dump(self.hardware_report, f, indent=2)
                messagebox.showinfo("Export", f"Report saved to {path}")
            except Exception as e:
                messagebox.showerror("Export Error", str(e))

    # ─── Update Logic ────────────────────────────────────────────────

    def _get_local_version(self):
        version_path = os.path.join(ROOT_DIR, "VERSION")
        try:
            with open(version_path, "r") as f:
                return f.read().strip()
        except Exception:
            return "0.0.0"

    def _parse_version(self, version_str):
        try:
            parts = version_str.strip().split(".")
            nums = [int(p) for p in parts]
            while len(nums) < 4:
                nums.append(0)
            return tuple(nums[:4])
        except Exception:
            return (0, 0, 0, 0)

    def check_for_updates(self):
        self.update_btn.configure(state="disabled", text="Checking...")
        self.update_status_lbl.configure(text="Checking for updates...", text_color=MUTED)

        def _do_check():
            try:
                import urllib.request
                import urllib.error
                import ssl
                import subprocess

                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                api_headers = {
                    "User-Agent": "LlamaCppBuildAssistant"
                }

                local_sha = None
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        capture_output=True, text=True, timeout=5, cwd=ROOT_DIR
                    )
                    if result.returncode == 0:
                        local_sha = result.stdout.strip()
                except Exception:
                    pass

                version_url = "https://api.github.com/repos/nextscript/Llama.cpp-Build-Assistant/contents/VERSION?ref=main"
                req_ver = urllib.request.Request(version_url, headers={**api_headers, "Accept": "application/vnd.github.v3.raw"})
                try:
                    with urllib.request.urlopen(req_ver, timeout=15, context=ssl_context) as resp_ver:
                        remote_version = resp_ver.read().decode().strip()
                except urllib.error.HTTPError as e:
                    if e.code == 403:
                        self.after(0, lambda: self._update_check_done(False, "Up to date."))
                        return
                    raise

                local_version = self._get_local_version()

                if self._parse_version(remote_version) <= self._parse_version(local_version):
                    self.after(0, lambda: self._update_check_done(False, "Up to date."))
                    return

                changed_files = []
                commit_msg = f"Update to v{remote_version}"

                if local_sha:
                    compare_url = f"https://api.github.com/repos/nextscript/Llama.cpp-Build-Assistant/compare/{local_sha}...main"
                    req_compare = urllib.request.Request(compare_url, headers=api_headers)
                    try:
                        with urllib.request.urlopen(req_compare, timeout=15, context=ssl_context) as resp_compare:
                            compare_data = json.loads(resp_compare.read().decode())

                        if compare_data.get("status") == "identical":
                            self.after(0, lambda: self._update_check_done(False, "Up to date."))
                            return

                        commits = compare_data.get("commits", [])
                        files = compare_data.get("files", [])

                        version_commits = [c for c in commits if remote_version in c["commit"]["message"]]
                        
                        if version_commits:
                            commit_msg = version_commits[0]["commit"]["message"].split("\n")[0]
                        
                        changed_files = list(set(f["filename"] for f in files))
                        
                    except urllib.error.HTTPError as e:
                        if e.code == 403 or e.code == 404:
                            changed_files = ["(see commit history)"]
                        else:
                            raise
                else:
                    changed_files = ["(see commit history)"]

                if not changed_files:
                    changed_files = ["(see commit history)"]

                self.after(0, lambda: self._show_update_modal(local_version, remote_version, changed_files, commit_msg))

            except Exception as e:
                err_msg = str(e) if str(e) else type(e).__name__
                self.after(0, lambda: self._update_check_done(False, f"Update check failed: {err_msg}"))

        threading.Thread(target=_do_check, daemon=True).start()

    def _update_check_done(self, has_update, msg):
        self.update_btn.configure(state="normal", text="Check for Updates")
        color = GREEN if has_update else MUTED
        self.update_status_lbl.configure(text=msg, text_color=color)

    def _show_update_modal(self, local_version, remote_version, changed_files, commit_msg):
        self.update_btn.configure(state="normal", text="Check for Updates")
        self.update_status_lbl.configure(text="Update available!", text_color=GREEN)

        modal = ctk.CTkToplevel(self)
        modal.title("Application Update")
        modal.geometry("700x550")
        modal.configure(fg_color=BG)
        modal.resizable(False, False)
        modal.transient(self)
        modal.grab_set()

        ctk.CTkLabel(modal, text="Update Available",
                      font=ctk.CTkFont(size=20, weight="bold"),
                      text_color=GREEN).pack(pady=(20, 5))

        info_frame = ctk.CTkFrame(modal, fg_color=SURFACE, corner_radius=8, border_width=1, border_color=BORDER)
        info_frame.pack(fill="x", padx=20, pady=8)

        ctk.CTkLabel(info_frame, text=f"Current version: v{local_version}",
                      font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            padx=15, pady=(10, 2), anchor="w")
        ctk.CTkLabel(info_frame, text=f"New version: v{remote_version}",
                      font=ctk.CTkFont(size=13, weight="bold"), text_color=GREEN).pack(
            padx=15, pady=(2, 2), anchor="w")
        ctk.CTkLabel(info_frame, text=f"Commit: {commit_msg}",
                      font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            padx=15, pady=(2, 10), anchor="w")

        files_frame = ctk.CTkFrame(modal, fg_color=SURFACE, corner_radius=8, border_width=1, border_color=BORDER)
        files_frame.pack(fill="both", expand=True, padx=20, pady=8)

        ctk.CTkLabel(files_frame, text=f"Changed files ({len(changed_files)}):",
                      font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT).pack(
            padx=15, pady=(10, 5), anchor="w")

        log_text = ctk.CTkTextbox(files_frame, font=ctk.CTkFont(size=11), corner_radius=8,
                                   fg_color="#070b11", text_color="#c7f89a",
                                   border_color=BORDER, border_width=1,
                                   scrollbar_button_color="#334155",
                                   scrollbar_button_hover_color="#475569")
        log_text.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        for f in changed_files:
            log_text.insert("end", f"  {f}\n")
        log_text.see("1.0")

        btn_frame = ctk.CTkFrame(modal, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(5, 15))

        download_btn = ctk.CTkButton(btn_frame, text="Download & Install Update",
                                      corner_radius=8, height=42,
                                      fg_color=BLUE, hover_color=BLUE_HOVER,
                                      font=ctk.CTkFont(size=14, weight="bold"))

        cancel_btn = ctk.CTkButton(btn_frame, text="Cancel",
                                    corner_radius=8, height=42,
                                    fg_color=SURFACE, hover_color="#172235",
                                    border_width=1, border_color=BORDER,
                                    text_color=TEXT,
                                    font=ctk.CTkFont(size=14, weight="bold"),
                                    command=modal.destroy)
        cancel_btn.pack(side="right", padx=5)

        def do_download():
            download_btn.configure(state="disabled", text="Downloading...")
            cancel_btn.configure(state="disabled")
            log_text.delete("1.0", "end")

            def _download_worker():
                import urllib.request
                import base64
                import json

                files_to_download = list(changed_files)

                if "(see commit history)" in files_to_download:
                    self.after(0, lambda: log_text.insert("end", "Could not determine changed files, fetching full file list...\n"))
                    self.after(0, lambda: log_text.see("end"))
                    try:
                        tree_url = "https://api.github.com/repos/nextscript/Llama.cpp-Build-Assistant/git/trees/main?recursive=1"
                        req_tree = urllib.request.Request(tree_url, headers={
                            "User-Agent": "LlamaCppBuildAssistant",
                            "Accept": "application/vnd.github.v3+json"
                        })
                        with urllib.request.urlopen(req_tree, timeout=30) as resp:
                            tree_data = json.loads(resp.read().decode("utf-8"))
                        files_to_download = [
                            item["path"] for item in tree_data.get("tree", [])
                            if item["type"] == "blob"
                        ]
                    except Exception as e:
                        self.after(0, lambda err=e: log_text.insert("end", f"Failed to fetch file list: {err}\n"))
                        self.after(0, lambda: log_text.see("end"))
                        self.after(0, lambda: download_btn.configure(state="normal", text="Retry",
                                                                      command=do_download))
                        self.after(0, lambda: cancel_btn.configure(state="normal", text="Close"))
                        return

                total = len(files_to_download)
                success_count = 0
                fail_count = 0

                for i, filename in enumerate(files_to_download, 1):
                    self.after(0, lambda fn=filename, idx=i: log_text.insert("end", f"[{idx}/{total}] Downloading: {fn}...\n"))
                    self.after(0, lambda: log_text.see("end"))

                    try:
                        file_api = f"https://api.github.com/repos/nextscript/Llama.cpp-Build-Assistant/contents/{filename}?ref=main"
                        req = urllib.request.Request(file_api, headers={
                            "User-Agent": "LlamaCppBuildAssistant",
                            "Accept": "application/vnd.github.v3.raw"
                        })

                        with urllib.request.urlopen(req, timeout=30) as resp:
                            content = resp.read()

                        local_path = os.path.join(ROOT_DIR, filename)
                        local_dir = os.path.dirname(local_path)
                        if not os.path.exists(local_dir):
                            os.makedirs(local_dir, exist_ok=True)

                        with open(local_path, "wb") as f:
                            f.write(content)

                        success_count += 1
                        self.after(0, lambda fn=filename: log_text.insert("end", f"  -> OK: {fn}\n"))
                        self.after(0, lambda: log_text.see("end"))

                    except Exception as e:
                        fail_count += 1
                        self.after(0, lambda fn=filename, err=e: log_text.insert("end", f"  -> FAILED: {fn} ({err})\n"))
                        self.after(0, lambda: log_text.see("end"))

                    time.sleep(0.2)

                self.after(0, lambda: log_text.insert("end", "\n" + "=" * 50 + "\n"))
                self.after(0, lambda: log_text.insert("end", f"Update complete: {success_count} succeeded, {fail_count} failed.\n"))
                self.after(0, lambda: log_text.insert("end", "\nPlease restart the application to apply changes.\n"))
                self.after(0, lambda: log_text.see("end"))

                self.after(0, lambda: download_btn.configure(state="normal", text="Restart Now",
                                                              command=lambda: self._restart_app(modal)))
                self.after(0, lambda: cancel_btn.configure(state="normal", text="Close"))

            threading.Thread(target=_download_worker, daemon=True).start()

        download_btn.configure(command=do_download)
        download_btn.pack(side="right", padx=5)

    def _restart_app(self, modal):
        import sys
        modal.destroy()
        self.destroy()
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        os.execl(python, python, script)


# ─── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BuildAssistantApp()
    app.mainloop()
