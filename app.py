"""
Llama.cpp Build Assistant — Main GUI Application
Uses CustomTkinter for a modern dark-themed interface..
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import platform
import threading
import os
import json
import time
import queue
import sys
import shutil
from datetime import datetime
try:
    from PIL import Image
except Exception:
    Image = None

from config import (
    ROOT_DIR, BUNDLE_DIR, BUILDS_DIR, BUILD_SOURCES_FILE, BUILD_HISTORY_FILE,
    SYSTEM_REPORT_FILE, PROFILES_FILE,
    DEFAULT_BUILD_SOURCES, DEFAULT_BUILD_PROFILES,
    BUILD_TYPES, BUILD_TYPE_DISPLAY, BUILD_TYPE_FLAGS, get_dir_suffix
)
from app_settings import (
    BUILD_OUTPUT_DIRECTORY_KEY, WINDOW_POSITION_KEY, load_settings,
    normalize_window_position, save_setting,
    validate_build_output_directory, validate_windows_vulkan_path,
    CPU_TARGET_KEY, BUILD_JOBS_KEY, normalize_build_choices
)
from hardware_check import (run_full_check, get_recommendation, get_recommendation_reason,
                            select_profile_name, recommend_cuda_major)
from dependency_checker import check_all, get_missing_for_build_type, get_missing_programs_text
from dependency_installer import (
    has_winget, has_sudo, install_missing, check_after_install,
    get_linux_package_manager
)
from source_manager import (
    load_sources, save_sources, get_source_by_id,
    validate_source, get_default_source,
    add_source, edit_source, delete_source,
    get_remote_branches, RemoteBranchError
)
from builder import (
    run_build, save_build_result, get_build_history,
    get_error_explanation, get_build_path, get_checkout_version,
    extract_error_lines, CPU_TARGETS
)
from source_version import (
    check_source_version
)
from profile_manager import load_profiles, add_profile, edit_profile, delete_profile, get_profile_by_name
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


def cmake_option_is_off(flags, option_name):
    """Return whether the final explicit CMake value for an option is OFF."""
    if isinstance(flags, str):
        flags = [flags]
    state = None
    false_values = {"OFF", "FALSE", "NO", "N", "0"}
    true_values = {"ON", "TRUE", "YES", "Y", "1"}
    for flag in flags or []:
        expression = str(flag).strip()
        if not expression.upper().startswith("-D"):
            continue
        expression = expression[2:].strip()
        if "=" not in expression:
            continue
        key, value = expression.split("=", 1)
        key = key.split(":", 1)[0].strip().upper()
        value = value.strip().upper()
        if key != option_name.upper():
            continue
        if value in false_values:
            state = False
        elif value in true_values:
            state = True
    return state is False


class SearchableDropdown(ctk.CTkFrame):
    """Compact selector opening a searchable, scrollable popup."""

    MAX_POPUP_HEIGHT = 320

    def __init__(self, master, values=None, placeholder="Select an item...",
                 search_placeholder="Search...", command=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._values = list(values or [])
        self._value = ""
        self._placeholder = placeholder
        self._search_placeholder = search_placeholder
        self._command = command
        self._popup = None
        self._search = None
        self._results = None
        self._matches = []
        self._previous_grab = None

        self._trigger = ctk.CTkButton(
            self, text="", anchor="w", height=34, corner_radius=6,
            fg_color="#0b111a", hover_color="#121c29",
            border_width=1, border_color=BORDER, text_color=TEXT,
            command=self.toggle)
        self._trigger.pack(fill="both", expand=True)
        self._update_trigger()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def get(self):
        return self._value

    def set(self, value):
        self._value = value or ""
        self._update_trigger()
        self._render_results()

    def set_values(self, values):
        self._values = list(values or [])
        self._render_results()

    def set_command(self, command):
        self._command = command

    def set_state(self, state):
        self._trigger.configure(state=state)
        if state == "disabled":
            self.close()

    def toggle(self):
        if self._popup is not None and self._popup.winfo_viewable():
            self.close()
        else:
            self.open()

    def open(self):
        if self._trigger.cget("state") == "disabled":
            return
        if self._popup is None or not self._popup.winfo_exists():
            self._build_popup()

        self.update_idletasks()
        width = max(self.winfo_width(), 260)
        row_count = max(1, min(len(self._values), 7))
        height = min(self.MAX_POPUP_HEIGHT, 68 + row_count * 38)
        x = self.winfo_rootx()
        below_y = self.winfo_rooty() + self.winfo_height() + 4
        screen_height = self.winfo_screenheight()
        y = below_y if below_y + height <= screen_height - 12 else self.winfo_rooty() - height - 4
        # The parent source dialog is modal. Temporarily release its grab so
        # this popup can receive input, but do not grab the popup itself: a
        # popup grab would disable the source dialog's native close button.
        self._previous_grab = self.grab_current()
        if self._previous_grab is not None:
            try:
                self._previous_grab.grab_release()
            except Exception:
                pass
        self._popup.geometry(f"{width}x{height}+{x}+{max(4, y)}")
        self._popup.deiconify()
        self._popup.lift()
        self._search.delete(0, "end")
        self._render_results()
        self._search.focus_force()

    def close(self):
        if self._popup is not None and self._popup.winfo_exists():
            try:
                if self._popup.grab_current() is self._popup:
                    self._popup.grab_release()
            except Exception:
                pass
            self._popup.withdraw()
        previous_grab = self._previous_grab
        self._previous_grab = None
        if previous_grab is not None:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
            except Exception:
                pass

    def _build_popup(self):
        self._popup = ctk.CTkToplevel(self)
        self._popup.withdraw()
        self._popup.overrideredirect(True)
        self._popup.transient(self.winfo_toplevel())
        self._popup.configure(fg_color=BORDER)
        self._popup.bind("<Escape>", lambda _event: self.close())
        self._popup.bind("<FocusOut>", self._schedule_focus_check, add="+")
        self._popup.bind("<ButtonPress-1>", self._close_on_outside_click,
                         add="+")

        box = ctk.CTkFrame(
            self._popup, corner_radius=8, fg_color=SURFACE,
            border_width=1, border_color=BORDER)
        box.pack(fill="both", expand=True)
        self._search = self._style_popup_entry(ctk.CTkEntry(
            box, height=34, placeholder_text=self._search_placeholder))
        self._search.pack(fill="x", padx=10, pady=(10, 6))
        self._search.bind("<KeyRelease>", lambda _event: self._render_results())
        list_frame = ctk.CTkFrame(box, fg_color="transparent", corner_radius=0)
        list_frame.pack(fill="both", expand=True, padx=(10, 4), pady=(0, 10))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)
        self._results = tk.Listbox(
            list_frame, bg=SURFACE, fg=TEXT,
            selectbackground=BLUE, selectforeground=TEXT,
            borderwidth=0, highlightthickness=0, activestyle="none",
            exportselection=False, font=("Segoe UI", 11))
        self._results.grid(row=0, column=0, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(
            list_frame, command=self._results.yview,
            button_color="#334155", button_hover_color="#475569")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(5, 0))
        self._results.configure(yscrollcommand=scrollbar.set)
        self._results.bind("<ButtonRelease-1>", self._select_list_item)
        self._results.bind("<Return>", self._select_list_item)
        self._search.bind("<Down>", self._focus_results)

    @staticmethod
    def _style_popup_entry(entry):
        entry.configure(
            fg_color="#070b11", border_color="#3b82f6", border_width=1,
            text_color=TEXT, placeholder_text_color=MUTED)
        return entry

    def _render_results(self):
        if self._results is None or not self._results.winfo_exists():
            return
        # Avoid rebuilding a hidden popup. The native listbox can efficiently
        # hold thousands of values without creating one Tk widget per branch.
        if self._popup is None or not self._popup.winfo_viewable():
            return
        query = self._search.get().strip().casefold() if self._search else ""
        self._matches = [value for value in self._values
                         if not query or query in value.casefold()]
        self._results.delete(0, "end")
        if not self._matches:
            self._results.insert("end", "No matching branches")
            self._results.itemconfigure(0, fg=MUTED, selectbackground=SURFACE)
            return
        for value in self._matches:
            self._results.insert("end", value)
        if self._value in self._matches:
            selected_index = self._matches.index(self._value)
            self._results.selection_set(selected_index)
            self._results.activate(selected_index)
            self._results.see(selected_index)

    def _focus_results(self, _event=None):
        if self._matches:
            self._results.focus_set()
            if not self._results.curselection():
                self._results.selection_set(0)
                self._results.activate(0)
        return "break"

    def _select_list_item(self, _event=None):
        selection = self._results.curselection()
        if selection and selection[0] < len(self._matches):
            self._select(self._matches[selection[0]])

    def _select(self, value):
        self.set(value)
        self.close()
        if self._command is not None:
            self._command(value)

    def _update_trigger(self):
        label = self._value or self._placeholder
        color = TEXT if self._value else MUTED
        self._trigger.configure(text=f"{label}   ▾", text_color=color)

    def _schedule_focus_check(self, _event=None):
        self.after(30, self._close_if_focus_left)

    def _close_on_outside_click(self, event):
        if self._popup is None:
            return
        left = self._popup.winfo_rootx()
        top = self._popup.winfo_rooty()
        right = left + self._popup.winfo_width()
        bottom = top + self._popup.winfo_height()
        if not (left <= event.x_root < right and top <= event.y_root < bottom):
            self.close()
            return "break"

    def _close_if_focus_left(self):
        if self._popup is None or not self._popup.winfo_viewable():
            return
        focused = self._popup.focus_get()
        if focused is None or focused.winfo_toplevel() is not self._popup:
            self.close()

    def _on_destroy(self, event):
        if event.widget is self and self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass


def resource_path(relative_path):
    """Return a path that works in source runs and PyInstaller bundles."""
    return os.path.join(BUNDLE_DIR, relative_path)


# ─── Main Application ───────────────────────────────────────────────

class BuildAssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Llama.cpp Build Assistant")
        saved_settings = load_settings()
        saved_window_position = normalize_window_position(
            saved_settings.get(WINDOW_POSITION_KEY))
        geometry = "1600x1024"
        if saved_window_position is not None:
            x, y = saved_window_position
            geometry += f"{x:+d}{y:+d}"
        self.geometry(geometry)
        self.minsize(1200, 800)
        self.configure(fg_color=BG)
        self._logo_image = None
        self._tk_icon_image = None
        self._last_normal_window_position = saved_window_position
        self.protocol("WM_DELETE_WINDOW", self._close_application)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # State
        self.hardware_report = None
        self.dep_check_results = None
        self.selected_source = ctk.StringVar(value="main")
        self.selected_profile = ctk.StringVar(value="")
        self.selected_build_type = ctk.StringVar(value="CPU")
        saved_build_output = saved_settings.get(BUILD_OUTPUT_DIRECTORY_KEY, BUILDS_DIR)
        if not isinstance(saved_build_output, str) or not saved_build_output.strip():
            saved_build_output = BUILDS_DIR
        self.build_output_dir_var = ctk.StringVar(value=saved_build_output)
        self.build_sources = load_sources()
        self.build_profiles = load_profiles()
        self.is_building = False
        self._source_name_to_id = {}
        self._profile_name_to_profile = {}
        self._build_log_queue = queue.Queue()
        self._ui_queue = queue.Queue()
        self._profile_manually_selected = False
        self._dependency_check_running = False
        self._source_version_generation = 0
        self._source_version_result = None
        self._resize_stable_size = None
        self._resize_frozen = False
        self._resize_thaw_job = None

        self._setup_window_icon()

        # Build UI
        self._build_ui()
        self.after(100, self._process_ui_queue)
        self.after(300, self._setup_window_icon)

        # Auto-run hardware check on start
        self.after(500, self.run_hardware_check)

    def _post_ui(self, callback):
        self._ui_queue.put(callback)

    def _update_dimensions_event(self, event=None):
        # Toplevel bindings also receive descendant Configure events. Moving
        # the native window does not require recalculating CTk dimensions.
        if event is not None:
            if event.widget is not self:
                return
            size = (event.width, event.height)
            position = (event.x, event.y)
            previous_position = getattr(self, "_last_window_position", None)
            previous_size = getattr(self, "_last_window_size", None)
            self._last_window_position = position
            self._last_window_size = size
            if self.state() == "normal":
                self._last_normal_window_position = position
            if previous_position is not None and (position != previous_position or size != previous_size):
                self._window_motion_until = time.monotonic() + 0.15
            if previous_size is not None and size != previous_size:
                self._on_window_resized(previous_size)
            if size == previous_size:
                return
        super()._update_dimensions_event(event)

    def _save_window_position(self):
        position = self._last_normal_window_position
        if position is None and self.state() == "normal":
            position = (self.winfo_x(), self.winfo_y())
        if position is not None:
            save_setting(WINDOW_POSITION_KEY, {"x": position[0], "y": position[1]})

    def _close_application(self):
        try:
            self._save_window_position()
        except OSError as exc:
            log_warning(f"Could not save window position: {exc}")
        self.destroy()

    def _on_window_resized(self, previous_size):
        # A full Tk relayout of this UI costs several hundred milliseconds.
        # On any resize (live window drag, Aero Snap previews, maximize) the
        # content is frozen at its last stable size and relaid out only once
        # the window has settled, instead of on every drag frame.
        if self._resize_stable_size is None:
            self._resize_stable_size = previous_size
        if not self._resize_frozen and hasattr(self, "_content_shell"):
            self._resize_frozen = True
            self._content_shell.place_configure(relwidth="", relheight="",
                                                width=self._resize_stable_size[0],
                                                height=self._resize_stable_size[1])
        if self._resize_thaw_job is not None:
            self.after_cancel(self._resize_thaw_job)
        self._resize_thaw_job = self.after(150, self._thaw_resize)

    def _thaw_resize(self):
        self._resize_thaw_job = None
        if not self._resize_frozen:
            return
        if not self.winfo_exists():
            return
        self._resize_frozen = False
        self._resize_stable_size = None
        self._content_shell.place_configure(width="", height="", relwidth=1, relheight=1)
        self.update_idletasks()

    def _process_ui_queue(self):
        if time.monotonic() < getattr(self, "_window_motion_until", 0):
            self.after(100, self._process_ui_queue)
            return
        # Limit work per tick so large bursts leave time for native window events.
        deadline = time.monotonic() + 0.008
        while time.monotonic() < deadline:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                self.report_callback_exception(*sys.exc_info())
        self._flush_build_log()
        self.after(100, self._process_ui_queue)

    def _card(self, parent, **kwargs):
        return ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=kwargs.pop("fg_color", SURFACE),
            border_width=1,
            border_color=BORDER,
            **kwargs
        )

    def _place_dialog(self, dialog):
        """Center a child dialog over the main window on the same monitor."""
        dialog.update_idletasks()
        parent = self.winfo_toplevel()
        width = max(dialog.winfo_width(), dialog.winfo_reqwidth())
        height = max(dialog.winfo_height(), dialog.winfo_reqheight())
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}{x:+d}{y:+d}")

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

    def _setup_window_icon(self):
        # Windows title bar: set a .ico via iconbitmap. CustomTkinter swaps in
        # its own icon ~200ms after init unless iconbitmap() has been called
        # (it tracks _iconbitmap_method_called), so iconphoto alone is lost.
        if sys.platform == "win32":
            self._set_app_user_model_id()
            ico_path = resource_path(os.path.join("build_assets", "icon.ico"))
            if os.path.exists(ico_path):
                try:
                    self.iconbitmap(ico_path)
                except Exception as exc:
                    log_warning(f"Could not set icon bitmap '{ico_path}': {exc}")
        # Linux window managers / Alt-Tab and cross-platform fallback.
        for filename in ("icon.png", "logo.png"):
            path = resource_path(filename)
            if not os.path.exists(path):
                continue
            try:
                import tkinter as tk
                self._tk_icon_photo = tk.PhotoImage(file=path)
                self.iconphoto(True, self._tk_icon_photo)
                return
            except Exception as exc:
                log_warning(f"Could not load app icon '{path}': {exc}")

    def _set_app_user_model_id(self):
        # Stable Windows app identity so taskbar/Alt-Tab show our icon instead
        # of grouping us under the Python interpreter.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "LlamaCppBuildAssistant")
        except Exception:
            pass

    def _create_logo_widget(self, parent):
        logo_path = resource_path("logo.png")
        if Image and os.path.exists(logo_path):
            try:
                image = Image.open(logo_path)
                self._logo_image = ctk.CTkImage(light_image=image, dark_image=image, size=(34, 34))
                return ctk.CTkLabel(parent, text="", image=self._logo_image,
                                    width=34, height=34)
            except Exception as exc:
                log_warning(f"Could not load GUI logo '{logo_path}': {exc}")
        return ctk.CTkLabel(parent, text="L", width=34, height=34, corner_radius=8,
                            fg_color=BLUE, text_color="white",
                            font=ctk.CTkFont(size=18, weight="bold"))

    def _build_ui(self):
        """Build the main GUI layout."""
        # Single shell holding the whole UI. It is managed via place() so the
        # layout can be frozen cheaply while the window is being dragged/resized.
        self._content_shell = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self._content_shell.place(x=0, y=0, relwidth=1, relheight=1)

        # ── Top bar ──
        top_frame = ctk.CTkFrame(self._content_shell, height=64, corner_radius=0, fg_color=BG)
        top_frame.pack(fill="x", padx=0, pady=0)
        top_frame.pack_propagate(False)

        logo = self._create_logo_widget(top_frame)
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
        body = ctk.CTkFrame(self._content_shell, fg_color=BG, corner_radius=0)
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
        if name == "Build" and hasattr(self, "version_status_values"):
            self.check_selected_source_version()

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
                                                text_color="#fbbf24",
                                                anchor="w", justify="left")
        self.lbl_recommendation.pack(padx=20, pady=(5, 15), anchor="w", fill="x")

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

        profile_frame = self._card(scroll_frame)
        profile_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(profile_frame, text="Build Profile:",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")

        self.profile_combo = self._style_combo(ctk.CTkComboBox(profile_frame, values=[],
                                                               variable=self.selected_profile,
                                                               command=self._on_manual_profile_changed,
                                                               corner_radius=8, height=36))
        self.profile_combo.pack(padx=20, pady=(5, 15), fill="x")
        self._update_profile_combo()

        version_frame = self._card(scroll_frame)
        version_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(version_frame, text="Build Version Status",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")
        version_grid = ctk.CTkFrame(version_frame, fg_color="transparent")
        version_grid.pack(fill="x", padx=20, pady=(0, 8))
        version_grid.grid_columnconfigure(1, weight=1, uniform="version_value")
        version_grid.grid_columnconfigure(3, weight=1, uniform="version_value")
        self.version_status_values = {}
        version_rows = (
            (("local_build", "Local Build:"),
             ("remote_build", "Latest Available:")),
            (("local_commit", "Local Commit:"),
             ("remote_commit", "Remote Commit:")),
            (("branch", "Branch:"),
             ("source_type", "Source Type:")),
            (("status", "Status:"),
             ("last_update", "Last Update:")),
        )
        for row_index, row_fields in enumerate(version_rows):
            for field_index, (key, label_text) in enumerate(row_fields):
                label_column = field_index * 2
                value_column = label_column + 1
                label_pad = (18, 0) if field_index else (0, 0)
                ctk.CTkLabel(
                    version_grid, text=label_text, width=108, anchor="w",
                    font=ctk.CTkFont(size=12), text_color=MUTED).grid(
                        row=row_index, column=label_column, sticky="w",
                        padx=label_pad, pady=3)
                value_label = ctk.CTkLabel(
                    version_grid, text="—", anchor="w", justify="left",
                    font=ctk.CTkFont(size=12))
                value_label.grid(
                    row=row_index, column=value_column, sticky="ew",
                    padx=(8, 0), pady=3)
                self.version_status_values[key] = value_label
        self.version_status_message = ctk.CTkLabel(
            version_frame, text="", anchor="w", justify="left",
            wraplength=760, font=ctk.CTkFont(size=11), text_color=MUTED)
        self.version_status_message.pack(fill="x", padx=20, pady=(0, 8))
        version_buttons = ctk.CTkFrame(version_frame, fg_color="transparent")
        version_buttons.pack(fill="x", padx=20, pady=(0, 15))
        self.check_source_version_btn = ctk.CTkButton(
            version_buttons, text="Check for Updates", width=145, height=34,
            command=self.check_selected_source_version,
            fg_color=SURFACE_ALT, hover_color="#172235")
        self.check_source_version_btn.pack(side="left")
        self.view_source_changes_btn = ctk.CTkButton(
            version_buttons, text="View Changes", width=125, height=34,
            command=self.view_source_changes, state="disabled",
            fg_color=SURFACE_ALT, hover_color="#172235")
        self.view_source_changes_btn.pack(side="left", padx=(8, 0))

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

        self.build_ui_var = ctk.BooleanVar(value=bool(shutil.which("npm") or shutil.which("npm.cmd")))
        self.build_ui_checkbox = ctk.CTkCheckBox(
            opt_frame,
            text="Build web UI with npm (unchecked: CMake downloads the prebuilt UI, needs internet)",
            variable=self.build_ui_var,
            font=ctk.CTkFont(size=13))
        self.build_ui_checkbox.pack(
            padx=20, pady=4, anchor="w")
        self._update_build_ui_option(self.selected_profile.get())

        self.core_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt_frame, text="Core tools only (llama-server, llama-cli, llama-bench, llama-quantize)",
                         variable=self.core_only_var,
                         font=ctk.CTkFont(size=13)).pack(
            padx=20, pady=4, anchor="w")

        row = ctk.CTkFrame(opt_frame, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(8, 4))
        ctk.CTkLabel(row, text="CPU target:", font=ctk.CTkFont(size=13)).pack(side="left")
        saved_target, saved_jobs = normalize_build_choices(load_settings())
        self.cpu_target_var = ctk.StringVar(value=saved_target)
        self.cpu_target_combo = self._style_combo(ctk.CTkComboBox(
            row, values=["portable", "native"], variable=self.cpu_target_var, width=130, height=30))
        self.cpu_target_combo.pack(side="left", padx=(8, 18))
        ctk.CTkLabel(row, text="Parallel jobs:", font=ctk.CTkFont(size=13)).pack(side="left")
        self.jobs_var = ctk.StringVar(value=str(saved_jobs))
        self.jobs_entry = self._style_field(ctk.CTkEntry(row, textvariable=self.jobs_var, width=70, height=30))
        self.jobs_entry.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(opt_frame, text="portable = AVX2/FMA/F16C, runs on any CPU since Haswell/Zen 1. "
                                     "native = tuned for this PC (AVX-512/AMX), not portable.",
                     font=ctk.CTkFont(size=11), text_color=MUTED, justify="left").pack(
            padx=20, pady=(0, 15), anchor="w")

        output_frame = self._card(scroll_frame)
        output_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(output_frame, text="Build Output Directory:",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=20, pady=(15, 8), anchor="w")
        output_row = ctk.CTkFrame(output_frame, fg_color="transparent")
        output_row.pack(fill="x", padx=20, pady=(5, 8))
        self.build_output_entry = self._style_field(ctk.CTkEntry(
            output_row, textvariable=self.build_output_dir_var, height=36))
        self.build_output_entry.pack(side="left", fill="x", expand=True)
        self.build_output_entry.bind("<FocusOut>", self._save_build_output_directory)
        self.build_output_entry.bind("<Return>", self._save_build_output_directory)
        ctk.CTkButton(output_row, text="Browse...", width=92, height=36,
                      command=self.browse_build_output_directory,
                      fg_color=SURFACE_ALT, hover_color="#172235").pack(
            side="left", padx=(8, 0))
        ctk.CTkButton(output_row, text="Reset to Default", width=125, height=36,
                      command=self.reset_build_output_directory,
                      fg_color=SURFACE_ALT, hover_color="#172235").pack(
            side="left", padx=(8, 0))
        ctk.CTkLabel(output_frame, text=f"Default: {BUILDS_DIR}",
                     font=ctk.CTkFont(size=11), text_color=MUTED,
                     justify="left", wraplength=760).pack(
            padx=20, pady=(0, 15), anchor="w")

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

        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkButton(btn_frame, text="Add Source",
                       command=self.add_source_dialog,
                       corner_radius=8, height=36,
                       fg_color=BLUE, hover_color=BLUE_HOVER).pack(
            side="left", padx=10, pady=15)

        self.sources_table = ctk.CTkScrollableFrame(frame, corner_radius=8, fg_color="#0d131d")
        self.sources_table.pack(fill="both", expand=True, padx=25, pady=8)
        self._update_sources_list()

    # ─── Profiles Tab ────────────────────────────────────────────────

    def _build_profiles_tab(self):
        frame = self.tab_profiles

        ctk.CTkLabel(frame, text="Build Profiles", font=ctk.CTkFont(size=24, weight="bold")).pack(
            padx=25, pady=(20, 10), anchor="w")

        btn_frame = self._card(frame)
        btn_frame.pack(fill="x", padx=25, pady=8)

        ctk.CTkButton(btn_frame, text="Add Profile",
                       command=self.add_profile_dialog,
                       corner_radius=8, height=36,
                       fg_color=BLUE, hover_color=BLUE_HOVER).pack(
            side="left", padx=10, pady=15)

        self.profiles_table = ctk.CTkScrollableFrame(frame, corner_radius=8, fg_color="#0d131d")
        self.profiles_table.pack(fill="both", expand=True, padx=25, pady=8)
        self._update_profiles_list()

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
                dep_results = check_all()
                self._post_ui(lambda: self._apply_hardware_check_results(report, dep_results))

            except Exception as e:
                err_msg = str(e)
                log_error(f"Hardware check failed: {err_msg}")
                self._post_ui(lambda: self.status_label.configure(text="Hardware check failed"))

        threading.Thread(target=_check, daemon=True).start()

    def _apply_hardware_check_results(self, report, dep_results):
        """Apply hardware/dependency results on the Tk main thread."""
        self.hardware_report = report
        self.dep_check_results = dep_results

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

        cuda_text = f"Available {gpu.get('cuda_version', '')}" if gpu.get("cuda_available") else "Not available"
        self.lbl_cuda.configure(text=f"CUDA: {cuda_text}")
        self.lbl_sycl.configure(text=f"SYCL: {'Available' if gpu.get('sycl_available') else 'Not available'}")
        self.lbl_os.configure(text=f"OS: {report.get('os', 'Unknown')}")
        self.lbl_disk.configure(text=f"Free Disk: {report.get('free_disk_gb', 0)} GB")

        rec = get_recommendation(report)
        selected_profile = (self.selected_profile.get() if self._profile_manually_selected
                            else self._select_profile_for_report(report))
        profile_hint = f"\nProfile: {selected_profile}" if selected_profile else ""
        cpu_hint = self._cpu_target_hint(report)
        self.lbl_recommendation.configure(
            text=f"Recommended: {BUILD_TYPE_DISPLAY.get(rec, rec)} Build "
                 f"({BUILD_TYPE_FLAGS.get(rec, '')}){profile_hint}\n"
                 f"{get_recommendation_reason(report)}\n{cpu_hint}")

        self._update_system_tab(report)
        self.status_label.configure(text="Hardware check complete")

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
        lines.append(f"  Architecture: {cpu.get('arch') or report.get('arch') or 'unknown'}")
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
                extra = ""
                if g.get("compute_cap"):
                    extra += f", compute capability {g['compute_cap']}"
                if g.get("unified_memory"):
                    extra += ", unified memory"
                lines.append(f"  {g.get('name', 'Unknown')} ({g.get('vendor', 'Unknown')}, "
                             f"{g.get('vram_gb', 0)} GB VRAM{extra})")
        else:
            lines.append("  None detected")
        lines.append("")

        lines.append("GPU Features:")
        lines.append(f"  NVIDIA: {'Yes' if gpu.get('has_nvidia') else 'No'}")
        if gpu.get('nvidia_driver_version'):
            lines.append(f"  Driver Version: {gpu['nvidia_driver_version']}")
        lines.append(f"  CUDA: {'Available' if gpu.get('cuda_available') else 'Not available'}")
        if gpu.get('cuda_version'):
            lines.append(f"  CUDA Toolkit: {gpu['cuda_version']}")
        if gpu.get('nvidia_driver_cuda_version'):
            lines.append(f"  CUDA supported by driver: up to {gpu['nvidia_driver_cuda_version']}"
                         f" (recommended toolkit: {recommend_cuda_major(report)}.x)")
        lines.append(f"  Vulkan: {'Available' if gpu.get('vulkan_available') else 'Not available'}")
        lines.append(f"  ROCm/HIP: {'Available' if gpu.get('rocm_available') else 'Not available'}")
        if gpu.get('amd_gfx_targets'):
            lines.append(f"  AMD gfx targets: {', '.join(gpu['amd_gfx_targets'])}")
        lines.append(f"  SYCL (Intel): {'Available' if gpu.get('sycl_available') else 'Not available'}")
        lines.append("")

        lines.append(f"Free Disk Space: {report.get('free_disk_gb', 0)} GB")
        lines.append("")

        rec = get_recommendation(report)
        lines.append(f"Recommended Build: {BUILD_TYPE_DISPLAY.get(rec, rec)} "
                      f"({BUILD_TYPE_FLAGS.get(rec, '')})")
        lines.append(f"  Why: {get_recommendation_reason(report)}")
        lines.append(f"  {self._cpu_target_hint(report)}")

        self.sys_text.delete("1.0", "end")
        self.sys_text.insert("1.0", "\n".join(lines))

    # ─── Dependencies ────────────────────────────────────────────────

    def check_dependencies(self):
        """Check all dependencies and display results."""
        if self._dependency_check_running:
            return
        self._dependency_check_running = True

        def worker():
            try:
                results = check_all()
                self._post_ui(lambda: self._display_dependencies(results))
            except Exception as exc:
                log_error(f"Dependency check failed: {exc}")
            finally:
                self._post_ui(lambda: setattr(self, "_dependency_check_running", False))

        threading.Thread(target=worker, daemon=True).start()

    def _display_dependencies(self, results):
        self.dep_check_results = results
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
            self.check_dependencies()
            messagebox.showinfo("Dependencies", "Dependency check started. Please retry when it completes.")
            return

        bt = self.selected_build_type.get()
        missing = get_missing_for_build_type(self.dep_check_results, bt)
        missing_names = get_missing_programs_text(missing)

        if not missing:
            messagebox.showinfo("Dependencies", "All dependencies are already installed!")
            return

        # Check platform support
        system = platform.system()
        if system == "Windows" and not shutil.which("winget"):
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

        def append_install_log(text):
            install_log.insert("end", text)
            install_log.see("end")

        def install_callback(line):
            self._post_ui(lambda line=line: append_install_log(line + "\n"))

        def do_install():
            results = install_missing(missing, callback=install_callback)
            all_ok = all(v[0] for v in results.values())

            if all_ok:
                self._post_ui(lambda: append_install_log(
                    "\n" + "=" * 40 + "\n"
                    "All installations completed successfully!\n"
                    "Re-checking dependencies...\n"
                ))

                # Re-check
                new_results = check_after_install()
                status_lines = []
                for name, info in new_results.items():
                    status = "OK" if info.get("found") else "STILL MISSING"
                    status_lines.append(f"  {name}: {status}")

                self.dep_check_results = new_results
                self._post_ui(lambda text="\n".join(status_lines): append_install_log(text + "\n"))
                self._post_ui(self.check_dependencies)
            else:
                failure_lines = ["", "=" * 40, "Some installations failed."]
                for dep, (success, msg) in results.items():
                    if not success:
                        failure_lines.append(f"  {dep}: {msg}")
                self._post_ui(lambda text="\n".join(failure_lines): append_install_log(text + "\n"))

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

    def _selected_build_source(self):
        source_name = self.selected_source.get()
        source_id = self._source_name_to_id.get(source_name, source_name)
        return get_source_by_id(source_id)

    def check_selected_source_version(self):
        """Check the selected source in a worker thread without blocking the UI."""
        source = self._selected_build_source()
        if not source:
            return

        self._source_version_generation += 1
        generation = self._source_version_generation
        self._source_version_result = None
        for label in self.version_status_values.values():
            label.configure(text="—", text_color=TEXT)
        self.version_status_values["status"].configure(text="Checking...", text_color=MUTED)
        self.version_status_message.configure(text="")
        self.check_source_version_btn.configure(state="disabled", text="Checking...")
        self.view_source_changes_btn.configure(state="disabled")

        build_output_dir = os.path.abspath(os.path.expanduser(
            self.build_output_dir_var.get().strip() or BUILDS_DIR))
        profile = get_profile_by_name(self.selected_profile.get())
        build_type = (profile or {}).get("build_type", self.selected_build_type.get())

        def worker():
            try:
                result = check_source_version(source, build_output_dir, build_type)
            except Exception as exc:
                result = {
                    "source_id": source.get("id", ""),
                    "status": "unable", "status_text": "Unable to check",
                    "message": str(exc), "update_allowed": False, "changes": []
                }
            self._post_ui(lambda: self._apply_source_version_result(generation, result))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_source_version_result(self, generation, result):
        if generation != self._source_version_generation:
            return
        self._source_version_result = result
        kind = result.get("kind", "custom")
        kind_labels = {
            "official": "Normal branch",
            "fork": "Fork",
            "custom": "Custom source",
            "pinned": "Pinned commit",
            "pr": f"PR #{result.get('pr', '')}",
        }
        source_type = kind_labels.get(kind, kind.title())
        if result.get("pinned") and kind == "pr":
            source_type += " (pinned)"
        if result.get("pr_state"):
            source_type += f" — {result['pr_state']}"

        def short_commit(value):
            return value[:9] if value else "Not available"

        values = {
            "local_build": result.get("local_build") or "Not available",
            "remote_build": result.get("remote_build") or "Not available",
            "status": result.get("status_text") or "Unable to check",
            "local_commit": short_commit(result.get("local_commit")),
            "remote_commit": short_commit(result.get("remote_commit")),
            "branch": result.get("branch") or "Not available",
            "source_type": source_type,
            "last_update": result.get("last_update") or "Not available",
        }
        status_colors = {
            "up_to_date": GREEN,
            "update_available": "#fbbf24",
            "pinned": "#60a5fa",
            "unable": DANGER,
            "not_built": MUTED,
        }
        for key, value in values.items():
            color = status_colors.get(result.get("status"), TEXT) if key == "status" else TEXT
            self.version_status_values[key].configure(text=value, text_color=color)

        details = []
        if result.get("pinned"):
            details.append("This source is pinned and will never be moved automatically.")
        if result.get("behind"):
            target = "PR commits" if kind == "pr" else "newer commits"
            details.append(f"{result['behind']} {target} available.")
        if result.get("ahead"):
            details.append(f"The local checkout is {result['ahead']} commits ahead of the remote target.")
        if result.get("message"):
            details.append(result["message"])
        self.version_status_message.configure(text=" ".join(details))

        self.view_source_changes_btn.configure(
            state="normal" if result.get("changes") else "disabled")
        self.check_source_version_btn.configure(state="normal", text="Check for Updates")

    def view_source_changes(self):
        """Show commits available between the local and remote source versions."""
        changes = (self._source_version_result or {}).get("changes", [])
        if not changes:
            messagebox.showinfo("Source Changes", "No new commits are available to display.")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Available Source Changes")
        dialog.geometry("760x520")
        dialog.transient(self)
        ctk.CTkLabel(dialog, text="Commits available upstream",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
            padx=20, pady=(18, 10), anchor="w")
        changes_text = self._style_textbox(ctk.CTkTextbox(
            dialog, font=ctk.CTkFont(size=12, family="Consolas")))
        changes_text.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        changes_text.insert("1.0", "\n".join(changes))
        changes_text.configure(state="disabled")

    def on_source_changed(self, source_name):
        source_id = self._source_name_to_id.get(source_name, source_name)
        source = get_source_by_id(source_id)
        if not source:
            return

        self.lbl_current_source.configure(text=source.get("name", source_id))
        if hasattr(self, "version_status_values"):
            self.check_selected_source_version()

    def on_profile_changed(self, profile_name):
        profile = get_profile_by_name(profile_name)
        if profile:
            self.selected_build_type.set(profile.get("build_type", "CPU"))
            # Profiles only pre-fill the options; the checkboxes decide at build time.
            if hasattr(self, "clean_build_var") and "clean_build" in profile:
                self.clean_build_var.set(bool(profile.get("clean_build")))
            if hasattr(self, "update_repo_var") and "update_repo" in profile:
                self.update_repo_var.set(bool(profile.get("update_repo")))
            self._update_build_ui_option(profile_name)
            if hasattr(self, "version_status_values"):
                self.check_selected_source_version()

    def _update_build_ui_option(self, profile_name):
        """Disable npm UI builds when the selected profile forces them off."""
        if not hasattr(self, "build_ui_checkbox"):
            return
        profile = get_profile_by_name(profile_name) or {}
        ui_disabled = cmake_option_is_off(
            profile.get("cmake_flags", []), "LLAMA_BUILD_UI")
        if ui_disabled:
            self.build_ui_var.set(False)
        self.build_ui_checkbox.configure(
            state="disabled" if ui_disabled else "normal")

    def _on_manual_profile_changed(self, profile_name):
        self._profile_manually_selected = True
        self.on_profile_changed(profile_name)

    def _queue_build_log(self, line):
        self._build_log_queue.put(line)

    def _save_build_output_directory(self, event=None):
        """Persist the currently selected build output directory."""
        selected = self.build_output_dir_var.get().strip()
        if not selected:
            return
        selected = os.path.abspath(os.path.expanduser(selected))
        self.build_output_dir_var.set(selected)
        try:
            save_setting(BUILD_OUTPUT_DIRECTORY_KEY, selected)
        except OSError as exc:
            messagebox.showerror(
                "Settings Error",
                f"The build output directory setting could not be saved.\n\n{exc}"
            )
        if event is not None and hasattr(self, "version_status_values"):
            self.check_selected_source_version()

    def browse_build_output_directory(self):
        """Select and persist a custom build output directory."""
        current = self.build_output_dir_var.get().strip()
        initial_directory = current if os.path.isdir(current) else BUILDS_DIR
        selected = filedialog.askdirectory(
            title="Select Build Output Directory",
            initialdir=initial_directory,
            mustexist=False
        )
        if selected:
            self.build_output_dir_var.set(os.path.abspath(selected))
            self._save_build_output_directory()
            self.check_selected_source_version()

    def reset_build_output_directory(self):
        """Restore and persist the application's default builds directory."""
        self.build_output_dir_var.set(BUILDS_DIR)
        self._save_build_output_directory()
        self.check_selected_source_version()

    def _flush_build_log(self):
        lines = []
        while not self._build_log_queue.empty() and len(lines) < 250:
            lines.append(self._build_log_queue.get_nowait())

        if lines:
            self.build_log_text.insert("end", "\n".join(lines) + "\n")
            line_count = int(self.build_log_text.index("end-1c").split(".")[0])
            if line_count > 5000:
                self.build_log_text.delete("1.0", f"{line_count - 5000 + 1}.0")
            self.build_log_text.see("end")

    def start_build(self):
        source_name = self.selected_source.get()
        source_id = self._source_name_to_id.get(source_name, source_name)
        source = get_source_by_id(source_id)
        profile_name = self.selected_profile.get()
        profile = get_profile_by_name(profile_name)

        if not source:
            messagebox.showerror("Error", f"Source '{source_id}' not found.")
            return

        if not profile:
            messagebox.showerror("Error", "Please select a valid build profile.")
            return

        # Check URL
        if not source.get("repo_url"):
            messagebox.showerror("Error",
                          "No repository URL configured for this build source.\n"
                          "Please configure the source in the Sources tab first.")
            return

        bt = profile.get("build_type", "CPU")
        self.selected_build_type.set(bt)

        try:
            validate_windows_vulkan_path(
                os.path.realpath(os.path.abspath(os.path.expanduser(self.build_output_dir_var.get().strip()))),
                bt, get_dir_suffix(source))
            build_output_dir, _free_bytes = validate_build_output_directory(
                self.build_output_dir_var.get())
            save_setting(BUILD_OUTPUT_DIRECTORY_KEY, build_output_dir)
            choices = {CPU_TARGET_KEY: self.cpu_target_var.get()}
            try:
                choices[BUILD_JOBS_KEY] = int(self.jobs_var.get().strip())
            except (TypeError, ValueError):
                pass
            saved_target, saved_jobs = normalize_build_choices(choices)
            save_setting(CPU_TARGET_KEY, saved_target)
            save_setting(BUILD_JOBS_KEY, saved_jobs)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Invalid Build Output Directory", str(exc))
            return
        self.build_output_dir_var.set(build_output_dir)

        # Clear log
        self.build_log_text.delete("1.0", "end")

        self.is_building = True
        self.build_btn.configure(state="disabled", text="Building...")
        self.status_label.configure(text="Building...")

        profile_flags = profile.get("cmake_flags", [])
        update_repo = self.update_repo_var.get()
        clean_build = self.clean_build_var.get()
        build_ui = (self.build_ui_var.get()
                    and not cmake_option_is_off(profile_flags, "LLAMA_BUILD_UI"))
        core_only = self.core_only_var.get()
        cpu_target = self.cpu_target_var.get() if self.cpu_target_var.get() in CPU_TARGETS else "portable"
        try:
            jobs = int(self.jobs_var.get().strip())
        except (TypeError, ValueError):
            jobs = 0
        cuda_major = str(profile.get("cuda_major", "") or "")

        def do_build():
            try:
                start_time = time.time()

                def callback(line):
                    self._queue_build_log(line)

                success, output, error_msg, binaries, build_path = run_build(
                    source_id, bt,
                    update_repo_flag=update_repo,
                    custom_flags=profile_flags,
                    clean_build=clean_build,
                    callback=callback,
                    build_ui=build_ui,
                    cpu_target=cpu_target,
                    jobs=jobs,
                    core_only=core_only,
                    cuda_major=cuda_major,
                    build_output_dir=build_output_dir
                )

                duration = time.time() - start_time

                # Save result
                if not build_path:
                    build_path = get_build_path(source_id, bt, build_output_dir)
                version_info = get_checkout_version(build_path)
                save_build_result(source_id, bt, success, build_path,
                                  binaries, duration, error_msg, version_info)

                if success:
                    self._queue_build_log("")
                    self._queue_build_log("=" * 60)
                    self._queue_build_log("BUILD SUCCESSFUL!")
                    self._queue_build_log(f"Duration: {duration:.1f} seconds")
                    if binaries:
                        self._queue_build_log(f"Binaries: {len(binaries)} found")
                        for b in binaries[:10]:
                            self._queue_build_log(f"  {b}")
                    self._post_ui(lambda: self.status_label.configure(text="Build successful!"))
                else:
                    self._queue_build_log("")
                    self._queue_build_log("=" * 60)
                    self._queue_build_log("BUILD FAILED!")
                    self._queue_build_log(f"Error: {error_msg}")

                    # Show the actual error lines, then an explanation
                    error_lines = extract_error_lines(output)
                    if error_lines:
                        self._queue_build_log("")
                        self._queue_build_log("Last error lines:")
                        for line in error_lines:
                            self._queue_build_log(f"  {line}")
                    explanation = get_error_explanation(error_msg, output)
                    self._queue_build_log("")
                    self._queue_build_log(f"Cause: {explanation['cause']}")
                    self._queue_build_log(f"Solution: {explanation['solution']}")
                    self._queue_build_log(f"Fallback: {explanation['fallback']}")

                    self._post_ui(lambda: self.status_label.configure(text="Build failed"))

            except Exception as e:
                self._queue_build_log("")
                self._queue_build_log(f"Unexpected error: {e}")
                log_error(f"Build error: {e}")
                self._post_ui(lambda: self.status_label.configure(text="Build error"))

            self.is_building = False
            self._post_ui(lambda: self.build_btn.configure(state="normal", text="Start Build"))
            self._post_ui(self.check_selected_source_version)

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
                if entry.get("build_number"):
                    lines.append(f"  Build: {entry['build_number']}")
                if entry.get("commit"):
                    lines.append(f"  Commit: {entry['commit']}")
                if entry.get("branch"):
                    lines.append(f"  Branch: {entry['branch']}")
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
        """Update the sources table."""
        sources = load_sources()
        for child in self.sources_table.winfo_children():
            child.destroy()

        columns = [("Name", 2), ("Repository URL", 4), ("Branch", 1), ("Commit", 2), ("Actions", 2)]
        for col, (text, weight) in enumerate(columns):
            self.sources_table.grid_columnconfigure(col, weight=weight)
            ctk.CTkLabel(self.sources_table, text=text,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT).grid(row=0, column=col, sticky="ew", padx=10, pady=(8, 6))

        if not sources:
            ctk.CTkLabel(self.sources_table, text="No sources configured.",
                         text_color=MUTED).grid(row=1, column=0, columnspan=5,
                                                sticky="w", padx=10, pady=12)
            return

        for row, source in enumerate(sources, start=1):
            commit = source.get("commit", "")
            short_commit = commit[:12] if commit else ""
            values = [
                source.get("name", ""),
                source.get("repo_url", ""),
                source.get("branch", ""),
                short_commit,
            ]
            for col, value in enumerate(values):
                ctk.CTkLabel(self.sources_table, text=value or "-",
                             anchor="w", justify="left",
                             wraplength=520 if col == 1 else 220).grid(
                    row=row, column=col, sticky="ew", padx=10, pady=6)

            action_frame = ctk.CTkFrame(self.sources_table, fg_color="transparent")
            action_frame.grid(row=row, column=4, sticky="e", padx=10, pady=6)
            ctk.CTkButton(action_frame, text="Edit", width=78, height=30,
                          corner_radius=8,
                          command=lambda s=source: self.source_dialog(s)).pack(side="left", padx=(0, 6))
            ctk.CTkButton(action_frame, text="Delete", width=78, height=30,
                          corner_radius=8, fg_color=DANGER, hover_color=DANGER_HOVER,
                          command=lambda s=source: self.delete_source_row(s)).pack(side="left")

    def add_source_dialog(self):
        """Show dialog to add a new source."""
        self.source_dialog()

    def source_dialog(self, source=None):
        """Show dialog to add or edit a source."""
        is_edit = source is not None
        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Build Source" if is_edit else "Add Build Source")
        dialog.geometry("600x650")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Edit Build Source" if is_edit else "Add Build Source",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(15, 5))

        fields = [
            ("Name:", "name", "my-fork", source.get("name", "") if is_edit else ""),
            ("Repository URL:", "url", "https://github.com/user/repo", source.get("repo_url", "") if is_edit else ""),
        ]

        entries = {}
        for label, key, placeholder, value in fields:
            ctk.CTkLabel(dialog, text=label).pack(pady=(5, 0), padx=20, anchor="w")
            entry = self._style_field(ctk.CTkEntry(dialog, placeholder_text=placeholder, height=34))
            if value:
                entry.insert(0, value)
            entry.pack(pady=2, padx=20, fill="x")
            entries[key] = entry

        custom_choice = "Custom branch..."
        loading_choice = "Loading branches..."
        unavailable_choice = "Branch detection unavailable"
        original_branch = source.get("branch", "") if is_edit else ""
        branch_state = {"branches": [], "url": "", "generation": 0,
                        "debounce_job": None, "closed": False,
                        "manual_selected": False}

        ctk.CTkLabel(dialog, text="Branch:").pack(pady=(5, 0), padx=20, anchor="w")
        branch_row = ctk.CTkFrame(dialog, fg_color="transparent")
        branch_row.pack(pady=2, padx=20, fill="x")
        branch_combo = SearchableDropdown(
            branch_row, values=[custom_choice], height=34,
            placeholder="Select a branch...",
            search_placeholder="Search branches...")
        branch_combo.pack(side="left", fill="x", expand=True)
        refresh_button = ctk.CTkButton(
            branch_row, text="Refresh", width=82, height=34,
            command=lambda: schedule_branch_load(
                immediate=True, reset_manual=False))
        refresh_button.pack(side="left", padx=(8, 0))

        custom_label = ctk.CTkLabel(dialog, text="Custom Branch:")
        custom_entry = self._style_field(ctk.CTkEntry(
            dialog, placeholder_text="branch or ref", height=34))
        if original_branch:
            custom_entry.insert(0, original_branch)
        branch_status = ctk.CTkLabel(dialog, text="Enter a repository URL",
                                     text_color=MUTED, anchor="w")
        branch_status.pack(pady=(3, 1), padx=20, fill="x")

        def show_custom(show=True):
            if show:
                if not custom_label.winfo_manager():
                    custom_label.pack(pady=(5, 0), padx=20, anchor="w",
                                      before=branch_status)
                    custom_entry.pack(pady=2, padx=20, fill="x",
                                      before=branch_status)
            else:
                custom_label.pack_forget()
                custom_entry.pack_forget()

        def branch_selected(choice):
            branch_state["manual_selected"] = choice == custom_choice
            show_custom(choice in (custom_choice, unavailable_choice))

        branch_combo.set_command(branch_selected)
        branch_combo.set(custom_choice)
        show_custom(True)

        for label, key, placeholder, value in [
            ("Pinned Commit (optional):", "commit", "full commit sha",
             source.get("commit", "") if is_edit else ""),
            ("Fetch Ref (optional):", "fetch_ref", "pull/17400/head",
             source.get("fetch_ref", "") if is_edit else ""),
        ]:
            ctk.CTkLabel(dialog, text=label).pack(pady=(5, 0), padx=20, anchor="w")
            entry = self._style_field(ctk.CTkEntry(dialog, placeholder_text=placeholder, height=34))
            if value:
                entry.insert(0, value)
            entry.pack(pady=2, padx=20, fill="x")
            entries[key] = entry

        def apply_branch_result(generation, url, branches=None, default_branch="", error=""):
            if branch_state["closed"] or not dialog.winfo_exists():
                return
            if generation != branch_state["generation"] or url != entries["url"].get().strip():
                return
            refresh_button.configure(state="normal")
            if error:
                branch_state["branches"] = []
                branch_state["url"] = url
                branch_combo.set_values([unavailable_choice, custom_choice])
                branch_combo.set(unavailable_choice)
                branch_status.configure(text=f"Could not load branches: {error}",
                                        text_color="#f59e0b")
                show_custom(True)
                return

            branch_state["branches"] = branches
            branch_state["url"] = url
            branch_combo.set_values(branches + [custom_choice])
            if branch_state["manual_selected"]:
                branch_combo.set(custom_choice)
                show_custom(True)
                status = f"Loaded {len(branches)} remote branches"
                if default_branch:
                    status += f" · Default: {default_branch}"
                branch_status.configure(text=status, text_color=GREEN)
                return
            editing_original_remote = (
                is_edit and url == source.get("repo_url", "").strip())
            if editing_original_remote and original_branch not in branches:
                branch_combo.set(custom_choice)
                show_custom(True)
                branch_status.configure(
                    text="Branch not found in remote repository",
                    text_color="#f59e0b")
                return
            if editing_original_remote:
                selected = original_branch
            elif "main" in branches:
                selected = "main"
            elif "master" in branches:
                selected = "master"
            elif default_branch in branches:
                selected = default_branch
            else:
                selected = branches[0]
            branch_combo.set(selected)
            show_custom(False)
            status = f"Loaded {len(branches)} remote branches"
            if default_branch:
                status += f" · Default: {default_branch}"
            branch_status.configure(text=status, text_color=GREEN)

        def load_branches(generation, url):
            try:
                branches, default_branch = get_remote_branches(url)
                error = ""
            except RemoteBranchError as exc:
                branches, default_branch, error = [], "", str(exc)
            except Exception as exc:
                branches, default_branch, error = [], "", str(exc)
            self._post_ui(lambda: apply_branch_result(
                generation, url, branches, default_branch, error))

        def start_branch_load():
            branch_state["debounce_job"] = None
            url = entries["url"].get().strip()
            branch_state["generation"] += 1
            generation = branch_state["generation"]
            branch_state["branches"] = []
            branch_state["url"] = url
            if not url:
                branch_combo.set_values([custom_choice])
                branch_combo.set(custom_choice)
                branch_status.configure(text="Enter a repository URL", text_color=MUTED)
                refresh_button.configure(state="normal")
                show_custom(True)
                return
            branch_combo.set_values([loading_choice, custom_choice])
            branch_combo.set(loading_choice)
            branch_status.configure(text=loading_choice, text_color=MUTED)
            refresh_button.configure(state="disabled")
            show_custom(False)
            threading.Thread(target=load_branches, args=(generation, url), daemon=True).start()

        def schedule_branch_load(*_args, immediate=False, reset_manual=True):
            job = branch_state.get("debounce_job")
            if job is not None:
                try:
                    dialog.after_cancel(job)
                except Exception:
                    pass
            branch_state["generation"] += 1
            branch_state["branches"] = []
            if reset_manual:
                branch_state["manual_selected"] = False
            delay = 0 if immediate else 300
            branch_state["debounce_job"] = dialog.after(delay, start_branch_load)

        entries["url"].bind("<KeyRelease>", schedule_branch_load, add="+")

        def save():
            name = entries["name"].get().strip()
            url = entries["url"].get().strip()
            choice = branch_combo.get()
            if choice in (custom_choice, unavailable_choice):
                branch = custom_entry.get().strip()
            elif choice == loading_choice:
                messagebox.showerror("Error", "Please wait until branch detection finishes.")
                return
            else:
                branch = choice.strip()
            commit = entries["commit"].get().strip()
            fetch_ref = entries["fetch_ref"].get().strip()

            if not name or not url or not branch:
                messagebox.showerror("Error", "Name, Repository URL and Branch are required.")
                return

            is_custom = choice in (custom_choice, unavailable_choice)
            current_branches = branch_state["branches"]
            if (is_custom and current_branches
                    and branch_state["url"] == url
                    and branch not in current_branches):
                messagebox.showerror(
                    "Error", "Branch not found in remote repository")
                return

            if is_edit:
                ok, msg = edit_source(source.get("id"), name=name, repo_url=url,
                                      branch=branch, commit=commit, fetch_ref=fetch_ref)
            else:
                ok, msg = add_source(name, url, branch, source_type="custom",
                                     experimental=False, commit=commit, fetch_ref=fetch_ref)
            if ok:
                self.build_sources = load_sources()
                self._update_sources_list()
                self._update_source_combo()
                close_dialog()
            else:
                messagebox.showerror("Error", msg)

        ctk.CTkButton(dialog, text="Save" if is_edit else "Add", command=save,
                      fg_color=BLUE, hover_color=BLUE_HOVER,
                      corner_radius=8, height=36).pack(pady=18)

        def close_dialog():
            branch_state["closed"] = True
            branch_state["generation"] += 1
            job = branch_state.get("debounce_job")
            if job is not None:
                try:
                    dialog.after_cancel(job)
                except Exception:
                    pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        self._place_dialog(dialog)
        if entries["url"].get().strip():
            schedule_branch_load(immediate=True)

    def edit_selected_source(self):
        """Edit the selected source."""
        messagebox.showinfo("Sources", "Use the Edit button in the source row.")

    def delete_selected_source(self):
        """Delete the selected source."""
        messagebox.showinfo("Sources", "Use the Delete button in the source row.")

    def delete_source_row(self, source):
        source_id = source.get("id")
        if source_id == "main":
            messagebox.showerror("Error", "Cannot delete the main source.")
            return

        result = messagebox.askyesno("Confirm Delete",
                                  f"Delete source '{source.get('name', source_id)}'?")
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
        else:
            self.selected_source.set("")

    # ─── Profiles Management ─────────────────────────────────────────

    def _update_profiles_list(self):
        """Update the profiles table."""
        profiles = load_profiles()
        for child in self.profiles_table.winfo_children():
            child.destroy()

        columns = [("Name", 2), ("Build Type", 1), ("CMake Flags", 4), ("Actions", 2)]
        for col, (text, weight) in enumerate(columns):
            self.profiles_table.grid_columnconfigure(col, weight=weight)
            ctk.CTkLabel(self.profiles_table, text=text,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT).grid(row=0, column=col, sticky="ew", padx=10, pady=(8, 6))

        if not profiles:
            ctk.CTkLabel(self.profiles_table, text="No build profiles configured.",
                         text_color=MUTED).grid(row=1, column=0, columnspan=4,
                                                sticky="w", padx=10, pady=12)
            return

        for row, profile in enumerate(profiles, start=1):
            flags = ", ".join(profile.get("cmake_flags", []))
            values = [
                profile.get("name", ""),
                profile.get("build_type", ""),
                flags,
            ]
            for col, value in enumerate(values):
                ctk.CTkLabel(self.profiles_table, text=value or "-",
                             anchor="w", justify="left",
                             wraplength=520 if col == 2 else 220).grid(
                    row=row, column=col, sticky="ew", padx=10, pady=6)

            action_frame = ctk.CTkFrame(self.profiles_table, fg_color="transparent")
            action_frame.grid(row=row, column=3, sticky="e", padx=10, pady=6)
            ctk.CTkButton(action_frame, text="Edit", width=78, height=30,
                          corner_radius=8,
                          command=lambda p=profile: self.profile_dialog(p)).pack(side="left", padx=(0, 6))
            ctk.CTkButton(action_frame, text="Delete", width=78, height=30,
                          corner_radius=8, fg_color=DANGER, hover_color=DANGER_HOVER,
                          command=lambda p=profile: self.delete_profile_row(p)).pack(side="left")

    def add_profile_dialog(self):
        """Show dialog to add a profile."""
        self.profile_dialog()

    def profile_dialog(self, profile=None):
        """Show dialog to add or edit a build profile."""
        is_edit = profile is not None
        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Build Profile" if is_edit else "Add Build Profile")
        dialog.geometry("560x320")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Edit Build Profile" if is_edit else "Add Build Profile",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(15, 5))

        ctk.CTkLabel(dialog, text="Name:").pack(pady=(5, 0), padx=20, anchor="w")
        name_entry = self._style_field(ctk.CTkEntry(dialog, placeholder_text="My Profile", height=34))
        if is_edit:
            name_entry.insert(0, profile.get("name", ""))
        name_entry.pack(pady=2, padx=20, fill="x")

        ctk.CTkLabel(dialog, text="Build Type:").pack(pady=(5, 0), padx=20, anchor="w")
        build_type_combo = self._style_combo(ctk.CTkComboBox(dialog, values=BUILD_TYPES, height=34))
        build_type_combo.set(profile.get("build_type", "CPU") if is_edit else "CPU")
        build_type_combo.pack(pady=2, padx=20, fill="x")

        def resize():
            dialog.update_idletasks()
            dialog.geometry(f"560x{max(320, dialog.winfo_reqheight() + 24)}")

        if is_edit:
            ctk.CTkLabel(dialog, text="CMake Flags (one per line):").pack(
                pady=(5, 0), padx=20, anchor="w")
            existing_flags = profile.get("cmake_flags") or []
            flags_text = self._style_textbox(
                ctk.CTkTextbox(dialog, height=200, wrap="word",
                                font=ctk.CTkFont(size=13, family="Consolas")))
            for flag in existing_flags:
                flags_text.insert("end", flag + "\n")
            flags_text.pack(pady=2, padx=20, fill="x")
        else:
            ctk.CTkLabel(dialog, text="CMake Flags (one flag per row):").pack(
                pady=(5, 0), padx=20, anchor="w")
            flags_container = ctk.CTkFrame(dialog, fg_color="transparent")
            flags_container.pack(fill="x", padx=20, pady=(2, 8))
            flag_rows = []  # (row frame, entry)

            def remove_flag_row(row_to_remove):
                """Remove the flag row that contains the - button."""
                flag_rows[:] = [item for item in flag_rows if item[0] is not row_to_remove]
                row_to_remove.destroy()
                for row, _ in flag_rows:
                    row.pack_forget()
                for row, _ in flag_rows:
                    row.pack(fill="x")
                resize()

            def create_flag_row(removable=False):
                new_row = ctk.CTkFrame(flags_container, fg_color="transparent")
                e = self._style_field(
                    ctk.CTkEntry(new_row, placeholder_text="-DGGML_CUDA=ON", height=34))
                if not removable:
                    add_btn = ctk.CTkButton(new_row, text="+", width=28, height=34,
                                            fg_color=SURFACE, hover_color="#172235",
                                            border_width=1, border_color=BLUE,
                                            command=lambda: create_flag_row(removable=True))
                if removable:
                    del_btn = ctk.CTkButton(new_row, text="-", width=28, height=34,
                                            fg_color=SURFACE, hover_color="#172235",
                                            border_width=1, border_color=BLUE,
                                            command=lambda r=new_row: remove_flag_row(r))
                e.pack(side="left", fill="x", expand=True, padx=(0, 6))
                if not removable:
                    add_btn.pack(side="left", padx=(4, 0))
                if removable:
                    del_btn.pack(side="left", padx=(0, 0))
                flag_rows.append((new_row, e))
                for row, _ in flag_rows:
                    row.pack_forget()
                for row, _ in flag_rows:
                    row.pack(fill="x")
                resize()

            create_flag_row()

        def save():
            name = name_entry.get().strip()
            build_type = build_type_combo.get()
            if is_edit:
                flags = [f.strip()
                         for f in flags_text.get("1.0", "end-1c").splitlines()
                         if f.strip()]
            else:
                flags = [e.get().strip() for _, e in flag_rows if e.get().strip()]

            if not name:
                messagebox.showerror("Error", "Name is required.")
                return

            if is_edit:
                original_name = profile.get("name")
                kwargs = {"build_type": build_type, "cmake_flags": flags}
                if name != original_name:
                    kwargs["name"] = name
                ok, msg = edit_profile(original_name, **kwargs)
            else:
                ok, msg = add_profile(name, "", build_type, flags)
            if ok:
                self.build_profiles = load_profiles()
                self._update_profiles_list()
                self._update_profile_combo()
                dialog.destroy()
            else:
                messagebox.showerror("Error", msg)

        ctk.CTkButton(dialog, text="Save" if is_edit else "Add", command=save,
                      fg_color=BLUE, hover_color=BLUE_HOVER,
                      corner_radius=8, height=36).pack(pady=18)

        resize()
        self._place_dialog(dialog)

    def delete_selected_profile(self):
        """Delete the selected profile."""
        messagebox.showinfo("Profiles", "Use the Delete button in the profile row.")

    def delete_profile_row(self, profile):
        name = profile.get("name")
        result = messagebox.askyesno("Confirm Delete", f"Delete profile '{name}'?")
        if not result:
            return

        ok, msg = delete_profile(name)
        if ok:
            self.build_profiles = load_profiles()
            self._update_profiles_list()
            self._update_profile_combo()
        else:
            messagebox.showerror("Error", msg)

    def apply_profile(self):
        """Apply a build profile to the current settings."""
        self.on_profile_changed(self.selected_profile.get())

    def _update_profile_combo(self):
        profiles = load_profiles()
        names = [p.get("name") for p in profiles if p.get("name")]
        self._profile_name_to_profile = {p.get("name"): p for p in profiles if p.get("name")}
        if hasattr(self, "profile_combo"):
            self.profile_combo.configure(values=names)
        current = self.selected_profile.get()
        if current in names:
            self.on_profile_changed(current)
        elif names:
            self.selected_profile.set(names[0])
            self.on_profile_changed(names[0])
        else:
            self.selected_profile.set("")

    def _select_profile_for_report(self, report):
        """Select the profile that fits the hardware report best."""
        name = select_profile_name(report, load_profiles())
        if name:
            self.selected_profile.set(name)
            self.on_profile_changed(name)
            return name
        self.selected_build_type.set(get_recommendation(report))
        return ""

    def _cpu_target_hint(self, report):
        """Explain what the chosen CPU target means for this machine."""
        features = set(report.get("cpu", {}).get("features", []))
        arch = report.get("arch") or report.get("cpu", {}).get("arch") or ""
        target = self.cpu_target_var.get() if hasattr(self, "cpu_target_var") else "portable"
        if arch == "arm64":
            return "CPU target: native (arm64 uses the compiler's own CPU detection)."
        if target == "native":
            return ("CPU target: native (requests GGML_NATIVE=ON). Detected: "
                    + (", ".join(sorted(features)) or "unknown")
                    + ". Effective instructions depend on compiler support and profile overrides.")
        if "AVX2" not in features and features:
            return "CPU target: portable (AVX2) - WARNING: this CPU reports no AVX2, choose 'native'."
        unused = [f for f in ("AVX512", "AMX") if f in features]
        if unused:
            return f"CPU target: portable (AVX2). This CPU also has {', '.join(unused)}; choose 'native' to use it."
        return "CPU target: portable (AVX2/FMA/F16C), matches this CPU."

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
        version_path = resource_path("VERSION")
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
        if getattr(sys, "frozen", False):
            import webbrowser
            webbrowser.open("https://github.com/nextscript/Llama.cpp-Build-Assistant/releases/latest")
            return
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
                        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), text=True, timeout=5, cwd=ROOT_DIR
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
                        self._post_ui(lambda: self._update_check_done(False, "Up to date."))
                        return
                    raise

                local_version = self._get_local_version()

                if self._parse_version(remote_version) <= self._parse_version(local_version):
                    self._post_ui(lambda: self._update_check_done(False, "Up to date."))
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
                            self._post_ui(lambda: self._update_check_done(False, "Up to date."))
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

                self._post_ui(lambda: self._show_update_modal(local_version, remote_version, changed_files, commit_msg))

            except Exception as e:
                err_msg = str(e) if str(e) else type(e).__name__
                self._post_ui(lambda: self._update_check_done(False, f"Update check failed: {err_msg}"))

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
                    self._post_ui(lambda: log_text.insert("end", "Could not determine changed files, fetching full file list...\n"))
                    self._post_ui(lambda: log_text.see("end"))
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
                        self._post_ui(lambda err=e: log_text.insert("end", f"Failed to fetch file list: {err}\n"))
                        self._post_ui(lambda: log_text.see("end"))
                        self._post_ui(lambda: download_btn.configure(state="normal", text="Retry",
                                                                      command=do_download))
                        self._post_ui(lambda: cancel_btn.configure(state="normal", text="Close"))
                        return

                total = len(files_to_download)
                success_count = 0
                fail_count = 0

                for i, filename in enumerate(files_to_download, 1):
                    self._post_ui(lambda fn=filename, idx=i: log_text.insert("end", f"[{idx}/{total}] Downloading: {fn}...\n"))
                    self._post_ui(lambda: log_text.see("end"))

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
                        self._post_ui(lambda fn=filename: log_text.insert("end", f"  -> OK: {fn}\n"))
                        self._post_ui(lambda: log_text.see("end"))

                    except Exception as e:
                        fail_count += 1
                        self._post_ui(lambda fn=filename, err=e: log_text.insert("end", f"  -> FAILED: {fn} ({err})\n"))
                        self._post_ui(lambda: log_text.see("end"))

                    time.sleep(0.2)

                self._post_ui(lambda: log_text.insert("end", "\n" + "=" * 50 + "\n"))
                self._post_ui(lambda: log_text.insert("end", f"Update complete: {success_count} succeeded, {fail_count} failed.\n"))
                self._post_ui(lambda: log_text.insert("end", "\nPlease restart the application to apply changes.\n"))
                self._post_ui(lambda: log_text.see("end"))

                self._post_ui(lambda: download_btn.configure(state="normal", text="Restart Now",
                                                              command=lambda: self._restart_app(modal)))
                self._post_ui(lambda: cancel_btn.configure(state="normal", text="Close"))

            threading.Thread(target=_download_worker, daemon=True).start()

        download_btn.configure(command=do_download)
        download_btn.pack(side="right", padx=5)

    def _restart_app(self, modal):
        import sys
        modal.destroy()
        try:
            self._save_window_position()
        except OSError as exc:
            log_warning(f"Could not save window position: {exc}")
        self.destroy()
        python = sys.executable
        script = os.path.abspath(sys.argv[0])
        os.execl(python, python, script)


# ─── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    app = BuildAssistantApp()
    app.mainloop()
