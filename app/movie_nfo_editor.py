import ipaddress
import os
import shutil
import sys
import tempfile
import traceback
import tkinter as tk
import xml.etree.ElementTree as ET
import webbrowser
import re
import json
from io import BytesIO
from threading import Thread
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageOps, ImageTk


SUPPORTED_TAGS = ("[Uncen-Leaked]", "[English-Sub]", "[UNCENSORED]", "[4K]")
DEFAULT_JAVDB_URL_TEMPLATE = "https://www.javdatabase.com/movies/{title}/"
DEFAULT_COUNTRY = "Japanese"
ACTOR_XML_FIELDS = ("name", "role", "type", "sortorder", "thumb")
REMOTE_IMAGE_MAX_BYTES = 12 * 1024 * 1024
REMOTE_IMAGE_SCHEMES = {"http", "https"}
REMOTE_IMAGE_ALLOWED_PORTS = {None, 80, 443}
MOVIE_XML_ORDER = (
    ("Title", "title"),
    ("OriginalTitle", "originaltitle"),
    ("Plot", "plot"),
    ("MPAA", "mpaa"),
    ("Country", "country"),
    ("Genre", "genre"),
    ("Premiered", "premiered"),
    ("Set", "set"),
)


def indent_xml(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent_xml(child, level + 1)
        elem[-1].tail = i
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i
        elif level == 0:
            elem.tail = "\n"
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def clean_name(text):
    return "".join(c for c in text if c not in r'<>:"/\\|?*')


def proper_case(text):
    return " ".join(word.capitalize() for word in text.split())


def extract_year(text):
    text = text.strip()
    if not text:
        return ""
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return text


def actor_sortorder_for_display(actor_element, index):
    sortorder = (actor_element.findtext("sortorder", "") or "").strip()
    if sortorder:
        return sortorder
    return str(index)


def build_movie_name(title, year="", tag="", original=""):
    title = clean_name((title.strip() or "Movie").upper())
    year = year.strip()
    tag = tag.strip()
    original = clean_name(proper_case(original.strip()))

    name = title
    if year:
        name += f" ({year})"
    if tag:
        name += f" {tag}"
    if original:
        name += f" - {original}"
    return name


def format_actor_list_row(sortorder, name, role, sort_width=3, name_width=20):
    display_sortorder = (sortorder or "?").strip() or "?"
    display_name = (name or "Unnamed Actor").strip() or "Unnamed Actor"
    display_role = (role or "No role").strip() or "No role"
    return f"{display_sortorder.rjust(sort_width)} | {display_name.ljust(name_width)} | {display_role}"


def build_poster_png_name(filename):
    stem, _ext = os.path.splitext((filename or "").strip())
    if not stem:
        stem = "MOVIE"
    return f"{stem}-poster.png"


def build_backdrop_png_names(filename, count):
    stem, _ext = os.path.splitext((filename or "").strip())
    if not stem:
        stem = "MOVIE"
    if count <= 1:
        return [f"{stem}-backdrop.png"]
    return [f"{stem}-backdrop{i}.png" for i in range(1, count + 1)]


def build_matching_video_filename(video_path, nfo_filename):
    stem, _ext = os.path.splitext((nfo_filename or "").strip())
    if not stem:
        stem = "MOVIE"
    _video_stem, video_ext = os.path.splitext(os.path.basename(video_path or ""))
    return f"{stem}{video_ext}"


def build_part_filename(filename, part_number):
    stem, ext = os.path.splitext((filename or "").strip())
    if not stem:
        stem = "MOVIE"
    safe_part_number = max(1, int(part_number))
    return f"{stem}-Part-{safe_part_number}{ext}"


def parse_multiline_links(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def parse_genre_values(text):
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def is_allowed_remote_image_url(url):
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() not in REMOTE_IMAGE_SCHEMES or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False

    hostname = (parsed.hostname or "").strip().casefold()
    if not hostname or hostname == "localhost":
        return False
    if parsed.port not in REMOTE_IMAGE_ALLOWED_PORTS:
        return False

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True

    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def fetch_remote_image_bytes(url, user_agent="JAVNFOCreator/1.0", timeout=4, max_bytes=REMOTE_IMAGE_MAX_BYTES):
    if not is_allowed_remote_image_url(url):
        return None

    try:
        request = Request(url, headers={"User-Agent": user_agent})
        with urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                return None

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        return None
                except ValueError:
                    pass

            image_bytes = response.read(max_bytes + 1)
            if len(image_bytes) > max_bytes:
                return None
            return image_bytes
    except Exception:
        return None


def format_loaded_genres(root):
    genre_values = [(genre.text or "").strip() for genre in root.findall("genre")]
    genre_values = [genre for genre in genre_values if genre]
    if genre_values:
        return ", ".join(genre_values)
    return root.findtext("genre", "") or ""


def tag_settings_path():
    return os.path.join(get_app_data_dir(), "JAVNFOCreator-tags.json")


def website_settings_path():
    return os.path.join(get_app_data_dir(), "JAVNFOCreator-websites.json")

def get_tag_lookup(tags=None):
    active_tags = tuple(tags or SUPPORTED_TAGS)
    return {tag.casefold(): tag for tag in active_tags}


def load_configured_tags():
    path = tag_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return list(SUPPORTED_TAGS)

    raw_tags = data.get("tags", [])
    cleaned_tags = []
    seen = set()
    for tag in raw_tags:
        cleaned = (tag or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned_tags.append(cleaned)
    return cleaned_tags or list(SUPPORTED_TAGS)


def save_configured_tags(tags):
    path = tag_settings_path()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"tags": list(tags)}, handle, indent=2)


def load_javdb_url_template():
    path = website_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_JAVDB_URL_TEMPLATE

    template = (data.get("javdb_url_template") or "").strip()
    if "{title}" not in template:
        return DEFAULT_JAVDB_URL_TEMPLATE
    return template


def save_javdb_url_template(template):
    path = website_settings_path()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"javdb_url_template": template}, handle, indent=2)


def build_javdb_url(template, title):
    return template.format(title=quote((title or "").strip()))


def normalize_supported_tag(text, tags=None):
    lookup = get_tag_lookup(tags)
    return lookup.get((text or "").strip().casefold(), (text or "").strip())


def detect_supported_tag(text, tags=None):
    text_to_check = text or ""
    lowered = text_to_check.casefold()
    for tag in tuple(tags or SUPPORTED_TAGS):
        if tag.casefold() in lowered:
            return tag
    return ""


def remove_supported_tags(text, tags=None):
    cleaned = text or ""
    for tag in tuple(tags or SUPPORTED_TAGS):
        cleaned = re.sub(re.escape(tag), "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def contains_supported_tag(text, tag, tags=None):
    if not text or not tag:
        return False
    normalized_tag = normalize_supported_tag(tag, tags)
    return normalized_tag.casefold() in text.casefold()


def get_error_log_path():
    return os.path.join(get_app_data_dir(), "JAVNFOCreator-error.log")


def get_app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_app_data_dir():
    appdata_root = os.environ.get("APPDATA") or os.path.expanduser("~")
    target_dir = os.path.join(appdata_root, "JAVNFOCreator")
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def log_exception(exc_type, exc_value, exc_traceback):
    log_path = get_error_log_path()
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("\n=== Unhandled Exception ===\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=handle)
    return log_path


def parse_xml_file(path):
    with open(path, "rb") as handle:
        xml_bytes = handle.read()
    return ET.ElementTree(ET.fromstring(xml_bytes))


def write_xml_file(root_element, path):
    xml_bytes = ET.tostring(root_element, encoding="utf-8")
    declaration = b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
    temp_handle = None
    temp_path = None
    try:
        temp_handle = tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=os.path.dirname(os.path.abspath(path)) or ".",
            prefix=".tmp-",
            suffix=os.path.splitext(path)[1] or ".xml",
        )
        temp_path = temp_handle.name
        temp_handle.write(declaration)
        temp_handle.write(xml_bytes)
        temp_handle.flush()
        temp_handle.close()
        temp_handle = None
        try:
            os.replace(temp_path, path)
        except PermissionError:
            with open(path, "wb") as handle:
                handle.write(declaration)
                handle.write(xml_bytes)
    finally:
        if temp_handle is not None:
            temp_handle.close()
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


class MovieNFOEditor:
    def __init__(self, root, host=None, configure_window=True, create_menu=True):
        self.root = root
        self.host = host or root
        self.configure_window = configure_window
        self.create_menu = create_menu
        if self.configure_window:
            self.root.title("JAV NFO Creator")
            self.root.geometry("1260x780")
        self.root.minsize(1040, 660)

        self.current_file = None
        self.current_video_file = None
        self.selected_actor_index = None
        self.actor_entries = {}
        self.actor_editor_var = tk.StringVar(value="Ready to add a new actor")
        self.actor_data = []
        self.actor_card_frames = []
        self.actor_empty_state = None
        self.actor_placeholder_cache = {}
        self.actor_thumb_cache = {}
        self.actor_thumb_requests = {}
        self.actor_preview_cache = {}
        self.poster_preview_request_url = None
        self.poster_preview_image = None
        self.poster_preview_loading_url = None
        self.poster_preview_rendered_url = None
        self.poster_preview_rendered_size = None
        self.poster_preview_last_canvas_width = None
        self.collapsible_sections = {}
        self.actor_mousewheel_targets = []
        self.form_mousewheel_targets = []
        self.poster_mousewheel_targets = []
        self.widget_history = {}
        self.widget_redo_history = {}
        self._history_restore_in_progress = False
        self.current_editor_tab = "movie"
        self.editor_tab_buttons = {}
        self.supported_tags = load_configured_tags()
        self.javdb_url_template = load_javdb_url_template()
        self.preview_var = None
        self.setup_style()
        self.create_ui()

    def setup_style(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.colors = {
            "page_bg": "#f8f9fa",
            "shell_bg": "#f8f9fa",
            "surface": "#ffffff",
            "surface_alt": "#f8f9fa",
            "surface_soft": "#f8f9fa",
            "border": "#dee2e6",
            "border_soft": "#e9ecef",
            "border_strong": "#ced4da",
            "text": "#212529",
            "muted": "#6c757d",
            "subtle": "#868e96",
            "accent": "#0d6efd",
            "accent_soft": "#e7f1ff",
            "accent_hover": "#0b5ed7",
            "selected": "#e7f1ff",
            "success": "#198754",
            "success_soft": "#eaf7f0",
            "warning": "#fd7e14",
            "warning_soft": "#fff1e6",
            "danger": "#dc3545",
            "danger_soft": "#fbeaec",
            "header_bg": "#f8f9fa",
        }

        self.root.configure(bg=self.colors["page_bg"])

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background=self.colors["page_bg"])
        style.configure("Shell.TFrame", background=self.colors["shell_bg"])
        style.configure("Card.TFrame", background=self.colors["surface"])
        style.configure("Surface.TFrame", background=self.colors["surface_alt"])
        style.configure("App.TLabel", background=self.colors["page_bg"], foreground=self.colors["muted"])
        style.configure("Shell.TLabel", background=self.colors["shell_bg"], foreground=self.colors["muted"])
        style.configure("Card.TLabel", background=self.colors["surface"], foreground=self.colors["text"])
        style.configure("Muted.TLabel", background=self.colors["surface"], foreground=self.colors["muted"])
        style.configure(
            "HeroTitle.TLabel",
            background=self.colors["shell_bg"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 17),
        )
        style.configure(
            "HeroBody.TLabel",
            background=self.colors["shell_bg"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=self.colors["header_bg"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "SectionMeta.TLabel",
            background=self.colors["header_bg"],
            foreground=self.colors["subtle"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Section.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["muted"],
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "App.TButton",
            padding=(12, 8),
            font=("Segoe UI Semibold", 9),
            background=self.colors["surface"],
            foreground=self.colors["text"],
            borderwidth=1,
            relief="flat",
            focusthickness=0,
        )
        style.map(
            "App.TButton",
            background=[("active", "#f2f6fb"), ("pressed", "#e8edf5"), ("disabled", "#f7f9fc")],
            foreground=[("disabled", "#9aa5b3")],
            bordercolor=[("active", self.colors["border_strong"]), ("disabled", self.colors["border"])],
        )
        style.configure(
            "Primary.TButton",
            padding=(12, 8),
            font=("Segoe UI Semibold", 9),
            background=self.colors["accent"],
            foreground="#ffffff",
            borderwidth=0,
            relief="flat",
            focusthickness=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.colors["accent_hover"]), ("pressed", "#1e4ead"), ("disabled", "#b8c8eb")],
            foreground=[("disabled", "#edf3ff")],
        )
        style.configure(
            "App.TCombobox",
            padding=6,
            arrowsize=15,
            fieldbackground=self.colors["surface_alt"],
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border_strong"],
            lightcolor=self.colors["surface_alt"],
            darkcolor=self.colors["surface_alt"],
        )
        style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", self.colors["surface_alt"])],
            selectbackground=[("readonly", self.colors["surface_alt"])],
            selectforeground=[("readonly", self.colors["text"])],
            bordercolor=[("focus", self.colors["accent"]), ("readonly", self.colors["border_strong"])],
        )
        style.configure(
            "App.TEntry",
            padding=7,
            fieldbackground=self.colors["surface_alt"],
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border_strong"],
            insertcolor=self.colors["text"],
            lightcolor=self.colors["surface_alt"],
            darkcolor=self.colors["surface_alt"],
        )
        style.map(
            "App.TEntry",
            fieldbackground=[("focus", "#ffffff")],
            bordercolor=[("focus", self.colors["accent"])],
        )
        style.configure(
            "App.TNotebook",
            background=self.colors["shell_bg"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 8),
        )
        style.configure(
            "App.TNotebook.Tab",
            background="#e7edf5",
            foreground=self.colors["muted"],
            padding=(16, 9),
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", self.colors["surface"]), ("active", "#eef3fa")],
            foreground=[("selected", self.colors["text"]), ("active", self.colors["text"])],
        )

        style.configure(
            "Vertical.TScrollbar",
            background="#ced4da",
            troughcolor="#f8f9fa",
            bordercolor="#f8f9fa",
            arrowcolor="#6c757d",
            relief="flat",
            width=12,
        )
        style.map("Vertical.TScrollbar", background=[("active", "#adb5bd")])

    def create_ui(self):
        self.host.columnconfigure(0, weight=1)
        self.host.rowconfigure(0, weight=1)
        self.setup_edit_context_menu()
        if self.create_menu:
            self.create_menu_bar()

        self.main_frame = ttk.Frame(self.host, padding=(16, 14, 16, 10), style="App.TFrame")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.main_frame.columnconfigure(0, weight=3)
        self.main_frame.columnconfigure(1, weight=2)
        self.main_frame.rowconfigure(0, weight=1)

        self.create_fields(self.main_frame)
        self.create_actor_table(self.main_frame)
        self.create_buttons(self.host)
        self.create_preview_bar(self.host)
        self.create_status_bar(self.host)
        self.root.report_callback_exception = self.handle_tk_exception
        self.bind_shortcuts()

    def handle_tk_exception(self, exc_type, exc_value, exc_traceback):
        log_path = log_exception(exc_type, exc_value, exc_traceback)
        messagebox.showerror(
            "Application Error",
            f"The application hit an unexpected error.\n\nDetails were saved to:\n{log_path}",
        )
        self.root.destroy()

    def bind_shortcuts(self):
        self.root.bind("<Control-o>", lambda event: self.load_nfo_dialog())
        self.root.bind("<Control-s>", lambda event: self.save_nfo())
        self.root.bind("<Control-S>", lambda event: self.save_as_nfo())
        self.root.bind("<Control-j>", lambda event: self.open_javdatabase_page())
        self.root.bind("<Delete>", self.handle_delete_shortcut)
        self.root.bind("<Escape>", lambda event: self.clear_actor_editor())

    def setup_edit_context_menu(self):
        self.edit_menu = tk.Menu(self.root, tearoff=0)
        self.edit_menu.add_command(label="Undo", command=lambda: self.invoke_edit_event("<<Undo>>"))
        self.edit_menu.add_command(label="Redo", command=lambda: self.invoke_edit_event("<<Redo>>"))
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Cut", command=lambda: self.invoke_edit_event("<<Cut>>"))
        self.edit_menu.add_command(label="Copy", command=lambda: self.invoke_edit_event("<<Copy>>"))
        self.edit_menu.add_command(label="Paste", command=lambda: self.invoke_edit_event("<<Paste>>"))
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Select All", command=self.select_all_in_focused_widget)

    def invoke_edit_event(self, event_name):
        widget = self.root.focus_get()
        if widget is not None:
            try:
                widget.event_generate(event_name)
            except tk.TclError:
                pass

    def get_widget_text_value(self, widget):
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            return widget.get()
        if isinstance(widget, tk.Text):
            return widget.get("1.0", "end-1c")
        return None

    def set_widget_text_value(self, widget, value):
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.delete(0, tk.END)
            widget.insert(0, value)
            widget.icursor(tk.END)
        elif isinstance(widget, tk.Text):
            widget.delete("1.0", tk.END)
            widget.insert("1.0", value)
            widget.mark_set(tk.INSERT, "end-1c")

    def ensure_widget_history(self, widget):
        if widget not in self.widget_history:
            current = self.get_widget_text_value(widget)
            self.widget_history[widget] = [current if current is not None else ""]
            self.widget_redo_history[widget] = []

    def record_widget_history(self, widget):
        if self._history_restore_in_progress:
            return
        current = self.get_widget_text_value(widget)
        if current is None:
            return
        self.ensure_widget_history(widget)
        history = self.widget_history[widget]
        if not history or history[-1] != current:
            history.append(current)
            if len(history) > 100:
                del history[:-100]
        self.widget_redo_history[widget] = []

    def schedule_widget_history_record(self, widget):
        if self._history_restore_in_progress:
            return
        widget.after_idle(lambda w=widget: self.record_widget_history(w) if w.winfo_exists() else None)

    def undo_widget_edit(self, widget):
        current = self.get_widget_text_value(widget)
        if current is None:
            return
        self.ensure_widget_history(widget)
        history = self.widget_history[widget]
        if len(history) < 2:
            return
        self.widget_redo_history.setdefault(widget, []).append(history.pop())
        previous = history[-1]
        self._history_restore_in_progress = True
        try:
            self.set_widget_text_value(widget, previous)
        finally:
            self._history_restore_in_progress = False

    def redo_widget_edit(self, widget):
        current = self.get_widget_text_value(widget)
        if current is None:
            return
        self.ensure_widget_history(widget)
        redo_history = self.widget_redo_history.setdefault(widget, [])
        if not redo_history:
            return
        next_value = redo_history.pop()
        self._history_restore_in_progress = True
        try:
            self.set_widget_text_value(widget, next_value)
        finally:
            self._history_restore_in_progress = False
        history = self.widget_history[widget]
        if not history or history[-1] != next_value:
            history.append(next_value)

    def handle_edit_shortcut(self, widget, event_name):
        if event_name == "<<Undo>>":
            self.undo_widget_edit(widget)
        elif event_name == "<<Redo>>":
            self.redo_widget_edit(widget)
        else:
            self.invoke_edit_event(event_name)
            self.schedule_widget_history_record(widget)
        return "break"

    def select_all_in_focused_widget(self, event=None):
        widget = event.widget if event is not None else self.root.focus_get()
        if widget is None:
            return "break"
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.selection_range(0, tk.END)
            widget.icursor(tk.END)
        elif isinstance(widget, tk.Text):
            widget.tag_add(tk.SEL, "1.0", tk.END)
            widget.mark_set(tk.INSERT, "1.0")
            widget.see(tk.INSERT)
        return "break"

    def show_edit_context_menu(self, event):
        widget = event.widget
        try:
            widget.focus_force()
        except tk.TclError:
            return
        try:
            self.edit_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.edit_menu.grab_release()

    def bind_edit_shortcuts_for_widget(self, widget):
        self.ensure_widget_history(widget)
        widget.bind("<Button-3>", self.show_edit_context_menu)
        widget.bind("<FocusIn>", lambda _event, w=widget: self.ensure_widget_history(w))
        widget.bind("<KeyRelease>", lambda _event, w=widget: self.record_widget_history(w))
        widget.bind("<Control-a>", self.select_all_in_focused_widget)
        widget.bind("<Control-A>", self.select_all_in_focused_widget)
        widget.bind("<Control-z>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Undo>>"))
        widget.bind("<Control-Z>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Undo>>"))
        widget.bind("<Control-y>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Redo>>"))
        widget.bind("<Control-Y>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Redo>>"))
        widget.bind("<Control-x>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Cut>>"))
        widget.bind("<Control-X>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Cut>>"))
        widget.bind("<Control-c>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Copy>>"))
        widget.bind("<Control-C>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Copy>>"))
        widget.bind("<Control-v>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Paste>>"))
        widget.bind("<Control-V>", lambda _event, w=widget: self.handle_edit_shortcut(w, "<<Paste>>"))

    def bind_descendant_edit_widgets(self, root_widget):
        for child in root_widget.winfo_children():
            if isinstance(child, (tk.Entry, ttk.Entry, tk.Text)):
                self.bind_edit_shortcuts_for_widget(child)
            self.bind_descendant_edit_widgets(child)

    def create_fields(self, parent):
        container = ttk.Frame(parent, style="App.TFrame")
        container.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        form_shell = tk.Frame(container, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        form_shell.grid(row=0, column=0, sticky="nsew")
        form_shell.grid_columnconfigure(0, weight=1)
        form_shell.grid_rowconfigure(0, weight=0)

        self.entries = {}
        self.text_fields = {}
        self.poster_link_var = tk.StringVar()
        self.poster_text_fields = {}
        form_shell.grid_rowconfigure(1, weight=1)

        tab_bar = tk.Frame(form_shell, bg=self.colors["surface"], padx=12, pady=6)
        tab_bar.grid(row=0, column=0, sticky="ew")
        tab_bar.grid_columnconfigure(0, weight=1)

        tab_strip = tk.Frame(tab_bar, bg=self.colors["surface_alt"], padx=4, pady=3)
        tab_strip.grid(row=0, column=0, sticky="w")

        self.editor_tab_buttons["movie"] = tk.Label(
            tab_strip,
            text="Movie Settings",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
        )
        self.editor_tab_buttons["movie"].grid(row=0, column=0, padx=(0, 4))
        self.editor_tab_buttons["movie"].bind("<Button-1>", lambda _event: self.set_editor_tab("movie"))

        self.editor_tab_buttons["poster"] = tk.Label(
            tab_strip,
            text="Poster",
            bg=self.colors["surface_alt"],
            fg=self.colors["muted"],
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
        )
        self.editor_tab_buttons["poster"].grid(row=0, column=1)
        self.editor_tab_buttons["poster"].bind("<Button-1>", lambda _event: self.set_editor_tab("poster"))

        content_host = tk.Frame(form_shell, bg=self.colors["surface"])
        content_host.grid(row=1, column=0, sticky="nsew")
        content_host.grid_columnconfigure(0, weight=1)
        content_host.grid_rowconfigure(0, weight=1)

        metadata_tab = ttk.Frame(content_host, style="Card.TFrame")
        poster_tab = ttk.Frame(content_host, style="Card.TFrame")
        self.editor_tab_frames = {
            "movie": metadata_tab,
            "poster": poster_tab,
        }
        metadata_tab.grid(row=0, column=0, sticky="nsew")
        poster_tab.grid(row=0, column=0, sticky="nsew")

        metadata_tab.columnconfigure(0, weight=1)
        metadata_tab.rowconfigure(0, weight=1)

        viewport = tk.Frame(metadata_tab, bg=self.colors["surface"])
        viewport.grid(row=0, column=0, sticky="nsew")
        viewport.grid_columnconfigure(0, weight=1)
        viewport.grid_rowconfigure(0, weight=1)

        self.form_canvas = tk.Canvas(
            viewport,
            bg=self.colors["surface"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.form_canvas.grid(row=0, column=0, sticky="nsew")

        self.form_scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.form_canvas.yview, style="Vertical.TScrollbar")
        self.form_scrollbar.grid(row=0, column=1, sticky="ns")
        self.form_canvas.configure(
            yscrollcommand=lambda first, last: (self.form_scrollbar.set(first, last), self.update_canvas_scrollbar(self.form_canvas, self.form_scrollbar))
        )

        form_content = ttk.Frame(self.form_canvas, style="Card.TFrame")
        self.form_content_window = self.form_canvas.create_window((0, 0), window=form_content, anchor="nw")
        form_content.columnconfigure(0, weight=1)

        self.form_canvas.bind(
            "<Configure>",
            lambda event: self.form_canvas.itemconfigure(self.form_content_window, width=event.width),
        )
        form_content.bind(
            "<Configure>",
            lambda _event: (
                self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")),
                self.update_canvas_scrollbar(self.form_canvas, self.form_scrollbar),
            ),
        )
        self.bind_form_mousewheel_target(self.form_canvas)
        self.bind_form_mousewheel_target(form_content)

        basic_card, basic = self.create_card_section(form_content, "Basic Info", 0)
        basic.columnconfigure(0, weight=3)
        basic.columnconfigure(1, weight=1)

        ttk.Label(basic, text="Title", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(basic, text="Tag", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 4))
        self.entries["Title"] = ttk.Entry(basic, style="App.TEntry")
        self.entries["Title"].grid(row=1, column=0, sticky="ew", pady=(0, 2))

        self.tag_var = tk.StringVar()
        self.tag_combo = ttk.Combobox(
            basic,
            style="App.TCombobox",
            textvariable=self.tag_var,
            values=["", *self.supported_tags],
            state="readonly",
        )
        self.tag_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(0, 2))
        self.tag_combo.bind("<Button-1>", lambda event: self.tag_combo.event_generate("<Down>"))

        details_card, details = self.create_card_section(form_content, "Details", 1)
        details.columnconfigure(0, weight=1)
        details.columnconfigure(1, weight=1)
        details.columnconfigure(2, weight=1)

        ttk.Label(details, text="Original Title", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.entries["OriginalTitle"] = ttk.Entry(details, style="App.TEntry")
        self.entries["OriginalTitle"].grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Label(details, text="Genre", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 4))
        ttk.Label(details, text="Country", style="Section.TLabel").grid(row=2, column=1, sticky="w", padx=(12, 0), pady=(0, 4))
        ttk.Label(details, text="Premiered", style="Section.TLabel").grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(0, 4))
        self.entries["Genre"] = ttk.Entry(details, style="App.TEntry")
        self.entries["Genre"].grid(row=3, column=0, sticky="ew", pady=(0, 2))

        self.entries["Country"] = ttk.Entry(details, style="App.TEntry")
        self.entries["Country"].grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=(0, 2))

        self.entries["Premiered"] = ttk.Entry(details, style="App.TEntry")
        self.entries["Premiered"].grid(row=3, column=2, sticky="ew", padx=(12, 0), pady=(0, 2))

        ttk.Label(details, text="Plot", style="Section.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 4))

        plot_frame = ttk.Frame(details, style="Card.TFrame")
        plot_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(0, 8))
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        self.text_fields["Plot"] = tk.Text(
            plot_frame,
            height=6,
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 10),
            bg=self.colors["surface_alt"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
        )
        self.text_fields["Plot"].grid(row=0, column=0, sticky="nsew")
        self.bind_form_mousewheel_target(self.text_fields["Plot"])

        self.plot_scrollbar = ttk.Scrollbar(
            plot_frame,
            orient="vertical",
            command=self.text_fields["Plot"].yview,
            style="Vertical.TScrollbar",
        )
        self.plot_scrollbar.grid(row=0, column=1, sticky="ns")
        self.text_fields["Plot"].configure(
            yscrollcommand=lambda first, last: (self.plot_scrollbar.set(first, last), self.update_text_scrollbar(self.text_fields["Plot"], self.plot_scrollbar))
        )

        ttk.Label(details, text="Set", style="Section.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.entries["Set"] = ttk.Entry(details, style="App.TEntry")
        self.entries["Set"].grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 2))

        poster_tab.columnconfigure(0, weight=1)
        poster_tab.rowconfigure(0, weight=1)

        poster_viewport = tk.Frame(poster_tab, bg=self.colors["surface"])
        poster_viewport.grid(row=0, column=0, sticky="nsew")
        poster_viewport.columnconfigure(0, weight=1)
        poster_viewport.rowconfigure(0, weight=1)

        self.poster_canvas = tk.Canvas(
            poster_viewport,
            bg=self.colors["surface"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.poster_canvas.grid(row=0, column=0, sticky="nsew")

        self.poster_scrollbar = ttk.Scrollbar(
            poster_viewport,
            orient="vertical",
            command=self.poster_canvas.yview,
            style="Vertical.TScrollbar",
        )
        self.poster_scrollbar.grid(row=0, column=1, sticky="ns")
        self.poster_canvas.configure(
            yscrollcommand=lambda first, last: (self.poster_scrollbar.set(first, last), self.update_canvas_scrollbar(self.poster_canvas, self.poster_scrollbar))
        )

        poster_content = ttk.Frame(self.poster_canvas, style="Card.TFrame")
        self.poster_content_window = self.poster_canvas.create_window((0, 0), window=poster_content, anchor="nw")
        poster_content.columnconfigure(0, weight=1)

        self.poster_canvas.bind("<Configure>", self.handle_poster_canvas_configure)
        poster_content.bind(
            "<Configure>",
            lambda _event: (
                self.poster_canvas.configure(scrollregion=self.poster_canvas.bbox("all")),
                self.update_canvas_scrollbar(self.poster_canvas, self.poster_scrollbar),
            ),
        )
        self.bind_poster_mousewheel_target(self.poster_canvas)
        self.bind_poster_mousewheel_target(poster_content)

        poster_card, poster = self.create_card_section(poster_content, "Poster", 0, pady=(0, 8))
        poster.columnconfigure(0, weight=1)
        poster.columnconfigure(1, weight=0)
        poster.rowconfigure(2, weight=1)
        self.poster_link_entry = ttk.Entry(poster, textvariable=self.poster_link_var, style="App.TEntry")
        self.poster_link_entry.grid(row=0, column=0, sticky="ew", pady=3)
        self.bind_poster_mousewheel_target(self.poster_link_entry)

        preview_frame = tk.Frame(
            poster,
            bg=self.colors["surface_soft"],
            padx=10,
            pady=10,
        )
        preview_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        preview_frame.columnconfigure(0, weight=1)
        self.poster_preview_frame = preview_frame
        self.poster_preview_label = tk.Label(
            preview_frame,
            bg=self.colors["surface_soft"],
            bd=0,
            cursor="arrow",
        )
        self.poster_preview_label.grid(row=0, column=0, sticky="n")
        self.bind_poster_mousewheel_target(self.poster_preview_label)

        self.poster_preview_status = ttk.Label(
            preview_frame,
            text="Paste a poster link to preview it here.",
            style="Muted.TLabel",
            anchor="center",
            justify="center",
        )
        self.poster_preview_status.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        backdrops_card, backdrops = self.create_card_section(poster_content, "Backdrops", 1, pady=(0, 0), collapsed=True)
        backdrops.columnconfigure(0, weight=1)
        backdrops.rowconfigure(0, weight=1)

        backdrop_frame = tk.Frame(
            backdrops,
            bg=self.colors["surface_soft"],
            padx=1,
            pady=1,
        )
        backdrop_frame.grid(row=0, column=0, sticky="ew")
        backdrop_frame.columnconfigure(0, weight=1)
        backdrop_frame.rowconfigure(0, weight=1)

        self.poster_text_fields["BackdropLinks"] = tk.Text(
            backdrop_frame,
            height=5,
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=7,
            font=("Segoe UI", 10),
            bg=self.colors["surface_alt"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            highlightthickness=1,
            highlightbackground=self.colors["border_soft"],
            highlightcolor=self.colors["accent"],
        )
        self.poster_text_fields["BackdropLinks"].grid(row=0, column=0, sticky="nsew")
        self.bind_poster_mousewheel_target(self.poster_text_fields["BackdropLinks"])

        self.backdrop_scrollbar = ttk.Scrollbar(
            backdrop_frame,
            orient="vertical",
            command=self.poster_text_fields["BackdropLinks"].yview,
            style="Vertical.TScrollbar",
        )
        self.backdrop_scrollbar.grid(row=0, column=1, sticky="ns")
        self.poster_text_fields["BackdropLinks"].configure(
            yscrollcommand=lambda first, last: (self.backdrop_scrollbar.set(first, last), self.update_text_scrollbar(self.poster_text_fields["BackdropLinks"], self.backdrop_scrollbar))
        )

        self.reset_country_default()
        self.bind_preview_updates()
        self.poster_link_var.trace_add("write", lambda *_args: self.schedule_poster_preview_update())
        self.update_poster_preview()
        self.bind_descendant_mousewheel_targets(form_content, self.bind_form_mousewheel_target, skip_classes=(ttk.Scrollbar,))
        self.bind_descendant_mousewheel_targets(poster_content, self.bind_poster_mousewheel_target, skip_classes=(ttk.Scrollbar,))
        self.bind_descendant_edit_widgets(form_content)
        self.bind_descendant_edit_widgets(poster_content)
        self.update_canvas_scrollbar(self.form_canvas, self.form_scrollbar)
        self.update_text_scrollbar(self.text_fields["Plot"], self.plot_scrollbar)
        self.update_canvas_scrollbar(self.poster_canvas, self.poster_scrollbar)
        self.update_text_scrollbar(self.poster_text_fields["BackdropLinks"], self.backdrop_scrollbar)
        self.refresh_editor_tabs()

    def create_actor_table(self, parent):
        actor_card = tk.Frame(
            parent,
            bg=self.colors["border_soft"],
            bd=0,
            highlightthickness=0,
            padx=1,
            pady=1,
        )
        actor_card.grid(row=0, column=1, sticky="nsew")
        outer = tk.Frame(actor_card, bg=self.colors["surface"], padx=14, pady=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=3)
        outer.rowconfigure(1, weight=1)

        header = tk.Frame(outer, bg=self.colors["surface"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        ttk.Label(header, text="Actors", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")

        editor_card = ttk.Frame(outer, style="Card.TFrame")
        editor_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        editor_card.columnconfigure(0, weight=1)
        editor_card.rowconfigure(3, weight=1)

        header = ttk.Frame(editor_card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Actor Editor", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.actor_editor_var, style="App.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))

        editor = ttk.Frame(editor_card, style="Card.TFrame")
        editor.grid(row=1, column=0, sticky="ew")
        editor.columnconfigure(0, weight=1)
        editor.columnconfigure(1, weight=1)

        ttk.Label(editor, text="Name", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(editor, text="Role", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 4))
        name_entry = ttk.Entry(editor, style="App.TEntry")
        name_entry.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        name_entry.bind("<Return>", lambda event: self.save_actor())
        self.actor_entries["Name"] = name_entry

        role_entry = ttk.Entry(editor, style="App.TEntry")
        role_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(0, 8))
        role_entry.bind("<Return>", lambda event: self.save_actor())
        self.actor_entries["Role"] = role_entry

        ttk.Label(editor, text="SortOrder", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 4))
        ttk.Label(editor, text="Type", style="Section.TLabel").grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(0, 4))
        sort_entry = ttk.Entry(editor, width=8, style="App.TEntry")
        sort_entry.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        sort_entry.bind("<Return>", lambda event: self.save_actor())
        self.actor_entries["SortOrder"] = sort_entry

        type_entry = ttk.Entry(editor, width=8, style="App.TEntry")
        type_entry.grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=(0, 8))
        type_entry.insert(0, "Actor")
        type_entry.state(["disabled"])
        self.actor_entries["Type"] = type_entry

        ttk.Label(editor, text="Thumb", style="Section.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 4))
        thumb_entry = ttk.Entry(editor, style="App.TEntry")
        thumb_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        thumb_entry.bind("<Return>", lambda event: self.save_actor())
        self.actor_entries["Thumb"] = thumb_entry

        btn_frame = ttk.Frame(editor_card, style="Card.TFrame")
        btn_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        btn_frame.columnconfigure(0, weight=1)

        ttk.Button(btn_frame, text="Add Actor", style="App.TButton", command=self.add_actor).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(btn_frame, text="Update", style="App.TButton", command=self.save_actor).grid(
            row=1, column=0, sticky="ew", pady=(6, 0)
        )
        ttk.Button(btn_frame, text="Clear", style="App.TButton", command=self.clear_actor_editor).grid(
            row=2, column=0, sticky="ew", pady=(6, 0)
        )
        ttk.Button(btn_frame, text="Remove", style="App.TButton", command=self.remove_actor).grid(
            row=3, column=0, sticky="ew", pady=(6, 0)
        )

        table_frame = ttk.Frame(outer, style="Card.TFrame")
        table_frame.grid(row=1, column=1, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)

        ttk.Label(table_frame, text="Actor List", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        list_frame = ttk.Frame(table_frame, style="Card.TFrame")
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.actor_canvas = tk.Canvas(
            list_frame,
            bg=self.colors["surface"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.actor_canvas.grid(row=0, column=0, sticky="nsew")

        self.actor_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.actor_canvas.yview, style="Vertical.TScrollbar")
        self.actor_scrollbar.grid(row=0, column=1, sticky="ns")
        self.actor_canvas.configure(
            yscrollcommand=lambda first, last: (self.actor_scrollbar.set(first, last), self.update_canvas_scrollbar(self.actor_canvas, self.actor_scrollbar))
        )

        self.actor_cards_frame = ttk.Frame(self.actor_canvas, style="Card.TFrame")
        self.actor_cards_window = self.actor_canvas.create_window((0, 0), window=self.actor_cards_frame, anchor="nw")
        self.actor_cards_frame.columnconfigure(0, weight=1)

        self.actor_cards_frame.bind(
            "<Configure>",
            lambda event: (
                self.actor_canvas.configure(scrollregion=self.actor_canvas.bbox("all")),
                self.update_canvas_scrollbar(self.actor_canvas, self.actor_scrollbar),
            ),
        )
        self.actor_canvas.bind(
            "<Configure>",
            lambda event: self.actor_canvas.itemconfigure(self.actor_cards_window, width=event.width),
        )
        self.bind_actor_mousewheel_target(self.actor_canvas)
        self.bind_actor_mousewheel_target(self.actor_cards_frame)
        self.bind_descendant_edit_widgets(editor_card)
        self.update_canvas_scrollbar(self.actor_canvas, self.actor_scrollbar)
        self.clear_actor_editor()

    def handle_delete_shortcut(self, event=None):
        focus_widget = self.root.focus_get()
        if self.selected_actor_index is not None or focus_widget in self.actor_entries.values():
            self.remove_actor()

    def remove_actor(self):
        if self.selected_actor_index is None:
            messagebox.showinfo("No Actor Selected", "Select an actor to remove.")
            return

        del self.actor_data[self.selected_actor_index]
        self.refresh_actor_list()
        self.clear_actor_editor()
        self.set_status("Actor removed", "warning")

    def on_actor_mousewheel(self, event):
        if event.delta:
            self.actor_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def bind_actor_mousewheel_target(self, widget):
        if widget in self.actor_mousewheel_targets:
            return
        widget.bind("<MouseWheel>", self.on_actor_mousewheel)
        self.actor_mousewheel_targets.append(widget)

    def set_editor_tab(self, tab_name):
        self.current_editor_tab = tab_name
        self.refresh_editor_tabs()

    def refresh_editor_tabs(self):
        for tab_name, frame in self.editor_tab_frames.items():
            if tab_name == self.current_editor_tab:
                frame.tkraise()

        for tab_name, button in self.editor_tab_buttons.items():
            selected = tab_name == self.current_editor_tab
            button.configure(
                bg=self.colors["surface"] if selected else "#e9eff6",
                fg=self.colors["text"] if selected else self.colors["muted"],
            )

    def on_form_mousewheel(self, event):
        if not self.canvas_has_vertical_overflow(self.form_canvas):
            return "break"
        if event.delta:
            self.form_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def on_poster_mousewheel(self, event):
        if not self.canvas_has_vertical_overflow(self.poster_canvas):
            return "break"
        if event.delta:
            self.poster_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def bind_form_mousewheel_target(self, widget):
        if widget in self.form_mousewheel_targets:
            return
        widget.bind("<MouseWheel>", self.on_form_mousewheel)
        self.form_mousewheel_targets.append(widget)

    def bind_poster_mousewheel_target(self, widget):
        if widget in self.poster_mousewheel_targets:
            return
        widget.bind("<MouseWheel>", self.on_poster_mousewheel)
        self.poster_mousewheel_targets.append(widget)

    def canvas_has_vertical_overflow(self, canvas):
        canvas.update_idletasks()
        bbox = canvas.bbox("all")
        if not bbox:
            return False
        content_height = bbox[3] - bbox[1]
        viewport_height = canvas.winfo_height()
        return content_height > viewport_height + 2

    def text_widget_has_vertical_overflow(self, widget):
        widget.update_idletasks()
        first, last = widget.yview()
        return first > 0.0 or last < 1.0

    def set_scrollbar_visibility(self, scrollbar, enabled):
        if enabled:
            if not scrollbar.winfo_ismapped():
                scrollbar.grid()
        else:
            if scrollbar.winfo_ismapped():
                scrollbar.grid_remove()

    def update_canvas_scrollbar(self, canvas, scrollbar):
        self.set_scrollbar_visibility(scrollbar, self.canvas_has_vertical_overflow(canvas))

    def update_text_scrollbar(self, widget, scrollbar):
        self.set_scrollbar_visibility(scrollbar, self.text_widget_has_vertical_overflow(widget))

    def bind_descendant_mousewheel_targets(self, root_widget, bind_target, skip_classes=()):
        for child in root_widget.winfo_children():
            if skip_classes and isinstance(child, skip_classes):
                continue
            bind_target(child)
            self.bind_descendant_mousewheel_targets(child, bind_target, skip_classes=skip_classes)

    def select_actor(self, index):
        if index < 0 or index >= len(self.actor_data):
            return

        self.selected_actor_index = index
        values = self.actor_data[self.selected_actor_index]
        self.actor_editor_var.set(f"Editing: {values[0] or 'Unnamed Actor'}")
        for key, value in zip(("Name", "Role", "Type", "SortOrder", "Thumb"), values):
            entry = self.actor_entries[key]
            if key == "Type":
                entry.state(["!disabled"])
                entry.delete(0, tk.END)
                entry.insert(0, value or "Actor")
                entry.state(["disabled"])
            else:
                entry.delete(0, tk.END)
                entry.insert(0, value)
        self.refresh_actor_card_selection()

    def clear_actor_editor(self):
        self.selected_actor_index = None
        self.actor_editor_var.set("Ready to add a new actor")
        for key, entry in self.actor_entries.items():
            if key == "Type":
                entry.state(["!disabled"])
                entry.delete(0, tk.END)
                entry.insert(0, "Actor")
                entry.state(["disabled"])
            else:
                entry.delete(0, tk.END)

        self.actor_entries["SortOrder"].insert(0, str(self.get_next_sort_order()))
        self.refresh_actor_card_selection()
        self.actor_entries["Name"].focus_set()

    def refresh_actor_list(self):
        current_view = self.actor_canvas.yview()
        for card in self.actor_card_frames:
            widget = card["card"] if isinstance(card, dict) else card
            if widget.winfo_exists():
                widget.destroy()
        self.actor_card_frames = []
        if self.actor_empty_state is not None and self.actor_empty_state.winfo_exists():
            self.actor_empty_state.destroy()
        self.actor_empty_state = None

        if not self.actor_data:
            self.actor_empty_state = tk.Frame(self.actor_cards_frame, bg=self.colors["surface"], padx=16, pady=24)
            self.actor_empty_state.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            self.actor_empty_state.grid_columnconfigure(0, weight=1)

            empty_title = tk.Label(
                self.actor_empty_state,
                text="No actors yet",
                bg=self.colors["surface"],
                fg=self.colors["text"],
                font=("Segoe UI Semibold", 12),
            )
            empty_title.grid(row=0, column=0, sticky="n")

            empty_body = tk.Label(
                self.actor_empty_state,
                text="Add an actor from the editor on the left to start building the cast list.",
                bg=self.colors["surface"],
                fg=self.colors["muted"],
                font=("Segoe UI", 9),
                wraplength=260,
                justify="center",
            )
            empty_body.grid(row=1, column=0, sticky="n", pady=(8, 0))
            self.actor_canvas.yview_moveto(0)
            return

        for index, values in enumerate(self.actor_data):
            self.actor_card_frames.append(self.create_actor_card(index, values))

        self.refresh_actor_card_selection()
        if self.actor_data and current_view:
            self.actor_canvas.yview_moveto(current_view[0])

    def create_actor_card(self, index, values):
        name = values[0] or "Unnamed Actor"
        role = values[1] or "No role"
        sortorder = values[3] or "?"
        thumb_url = values[4] or ""
        card_size = (176, 236)

        card = tk.Frame(
            self.actor_cards_frame,
            bg=self.colors["border_soft"],
            bd=0,
            highlightthickness=0,
            padx=1,
            pady=1,
            cursor="hand2",
        )
        card.grid(row=index, column=0, sticky="ew", pady=(0, 8))
        card.grid_columnconfigure(0, weight=1)

        body = tk.Frame(card, bg=self.colors["surface"], padx=8, pady=8, cursor="hand2")
        body.grid(row=0, column=0, sticky="ew")
        body.grid_columnconfigure(1, weight=1)

        media = tk.Frame(body, bg=self.colors["surface"], cursor="hand2")
        media.grid(row=0, column=0, sticky="nsw")
        media.grid_columnconfigure(0, weight=1)
        thumb_label = tk.Label(media, bg=self.colors["surface"], bd=0, cursor="hand2")
        thumb_label.grid(row=0, column=0, sticky="nsew")
        thumb_label.thumb_size = card_size

        content = tk.Frame(body, bg=self.colors["surface_soft"], cursor="hand2", padx=14, pady=12)
        content.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        content.grid_columnconfigure(0, weight=1)

        sort_label = tk.Label(
            content,
            text=f"#{sortorder}",
            bg=self.colors["accent_soft"],
            fg=self.colors["accent"],
            padx=8,
            pady=3,
            font=("Segoe UI Semibold", 8),
            cursor="hand2",
        )
        sort_label.grid(row=0, column=0, sticky="w")

        name_label = tk.Label(
            content,
            text=name,
            bg=self.colors["surface_soft"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 12),
            anchor="w",
            cursor="hand2",
            justify="left",
            wraplength=170,
        )
        name_label.grid(row=1, column=0, sticky="ew", pady=(10, 3))

        role_label = tk.Label(
            content,
            text=role,
            bg=self.colors["surface_soft"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            wraplength=170,
            justify="left",
            anchor="w",
            cursor="hand2",
        )
        role_label.grid(row=2, column=0, sticky="new")

        placeholder = self.get_actor_placeholder_image(name, size=card_size)
        thumb_label.configure(image=placeholder)
        thumb_label.image = placeholder
        if thumb_url:
            self.set_actor_thumb_image(thumb_label, thumb_url, name)
        bind_targets = [card, body, media, content, sort_label, name_label, role_label, thumb_label]
        for widget in bind_targets:
            widget.bind("<Button-1>", lambda _event, actor_index=index: self.select_actor(actor_index))
            self.bind_actor_mousewheel_target(widget)
        return {
            "card": card,
            "body": body,
            "thumb": thumb_label,
            "media": media,
            "content": content,
            "sort": sort_label,
            "name": name_label,
            "role": role_label,
        }

    def refresh_actor_card_selection(self):
        for index, card_view in enumerate(self.actor_card_frames):
            card = card_view["card"]
            if not card.winfo_exists():
                continue
            body = card_view["body"]
            thumb = card_view["thumb"]
            media = card_view["media"]
            content = card_view["content"]
            sort_label = card_view["sort"]
            name_label = card_view["name"]
            role_label = card_view["role"]
            selected = index == self.selected_actor_index
            card.configure(bg="#bad1ff" if selected else self.colors["border_soft"])
            body_bg = self.colors["surface"] if selected else self.colors["surface"]
            body.configure(bg=body_bg)
            media.configure(bg=body_bg)
            thumb.configure(bg=body_bg)
            content_bg = "#f4f8ff" if selected else self.colors["surface_soft"]
            content.configure(bg=content_bg)
            sort_label.configure(
                bg="#d7e5ff" if selected else self.colors["accent_soft"],
                fg="#214fbc" if selected else self.colors["accent"],
            )
            name_label.configure(bg=content_bg, fg=self.colors["text"])
            role_label.configure(bg=content_bg, fg="#4f688e" if selected else self.colors["muted"])

    def get_actor_placeholder_image(self, name, size=(72, 96)):
        key = ((name or "").strip().casefold() or "placeholder", size)
        cached = self.actor_placeholder_cache.get(key)
        if cached is not None:
            return cached

        initials = "".join(part[0] for part in (name or "Actor").split()[:2]).upper() or "A"
        width, height = size
        image = Image.new("RGB", (width, height), "#edf3fb")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=max(10, min(width, height) // 7), fill="#edf3fb", outline="#d5deec")
        bbox = draw.textbbox((0, 0), initials)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text(
            ((width - text_width) / 2, (height - text_height) / 2 - 2),
            initials,
            fill="#47607d",
        )
        photo = ImageTk.PhotoImage(image)
        self.actor_placeholder_cache[key] = photo
        return photo

    def set_actor_thumb_image(self, label, url, name):
        thumb_size = getattr(label, "thumb_size", (132, 182))
        cached = self.actor_thumb_cache.get(url)
        if cached is not None:
            image = cached if cached is not False else self.get_actor_placeholder_image(name, size=thumb_size)
            label.configure(image=image)
            label.image = image
            return

        listeners = self.actor_thumb_requests.setdefault(url, [])
        listeners.append((label, name, thumb_size))
        if len(listeners) > 1:
            return

        def worker():
            pil_image = self.fetch_actor_thumb(url)
            self.root.after(0, lambda: self.finish_actor_thumb_image(url, pil_image))

        Thread(target=worker, daemon=True).start()

    def fetch_actor_thumb(self, url):
        return fetch_remote_image_bytes(url)

    def prepare_actor_image(self, image_bytes, size):
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                converted = ImageOps.exif_transpose(image).convert("RGB")
                width, height = size
                bleed = max(8, height // 16)
                crop_box = (0, bleed, converted.width, max(bleed + 1, converted.height - bleed))
                tightened = converted.crop(crop_box) if converted.height > bleed * 2 else converted
                return ImageOps.fit(tightened, size, Image.Resampling.LANCZOS, centering=(0.5, 0.28))
        except Exception:
            return None

    def prepare_poster_image(self, image_bytes, size):
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                converted = ImageOps.exif_transpose(image).convert("RGB")
                return ImageOps.contain(converted, size, Image.Resampling.LANCZOS)
        except Exception:
            return None

    def clear_poster_preview(self, message):
        self.poster_preview_label.configure(image="", text="")
        self.poster_preview_label.image = None
        self.poster_preview_image = None
        self.poster_preview_rendered_url = None
        self.poster_preview_rendered_size = None
        self.poster_preview_status.configure(text=message)

    def show_poster_preview_image(self, prepared_image, message="Poster ready."):
        preview_image = ImageTk.PhotoImage(prepared_image)
        self.poster_preview_label.configure(image=preview_image, text="")
        self.poster_preview_label.image = preview_image
        self.poster_preview_image = preview_image
        self.poster_preview_status.configure(text=message)

    def save_image_bytes_as_png(self, image_bytes, path):
        with Image.open(BytesIO(image_bytes)) as image:
            image.convert("RGBA").save(path, format="PNG")

    def schedule_poster_preview_update(self):
        if hasattr(self, "_poster_preview_after_id") and self._poster_preview_after_id:
            self.root.after_cancel(self._poster_preview_after_id)
        self._poster_preview_after_id = self.root.after(250, self.update_poster_preview)

    def handle_poster_canvas_configure(self, event):
        self.poster_canvas.itemconfigure(self.poster_content_window, width=event.width)
        if self.poster_preview_last_canvas_width == event.width:
            return
        self.poster_preview_last_canvas_width = event.width
        self.handle_poster_preview_resize()

    def handle_poster_preview_resize(self, _event=None):
        poster_url = self.poster_link_var.get().strip()
        if not poster_url:
            return

        preview_size = self.get_poster_preview_size()
        if (
            poster_url == self.poster_preview_rendered_url
            and self.poster_preview_rendered_size == preview_size
        ):
            return

        cached_bytes = self.actor_preview_cache.get(poster_url)
        if not cached_bytes:
            return

        prepared = self.prepare_poster_image(cached_bytes, preview_size)
        if prepared is None:
            return

        self.poster_preview_rendered_url = poster_url
        self.poster_preview_rendered_size = preview_size
        self.show_poster_preview_image(prepared)

    def finish_actor_thumb_image(self, url, image_bytes):
        listeners = self.actor_thumb_requests.pop(url, [])
        photo = None
        if image_bytes is not None:
            self.actor_preview_cache[url] = image_bytes
            thumb_size = listeners[0][2] if listeners else (132, 182)
            thumb_image = self.prepare_actor_image(image_bytes, thumb_size)
            if thumb_image is not None:
                photo = ImageTk.PhotoImage(thumb_image)
                self.actor_thumb_cache[url] = photo
            else:
                self.actor_thumb_cache[url] = False
        else:
            self.actor_thumb_cache[url] = False

        for label, name, thumb_size in listeners:
            if not label.winfo_exists():
                continue
            image = photo or self.get_actor_placeholder_image(name, size=thumb_size)
            label.configure(image=image)
            label.image = image

    def update_poster_preview(self):
        self._poster_preview_after_id = None
        poster_url = self.poster_link_var.get().strip()
        self.poster_preview_request_url = poster_url
        preview_size = self.get_poster_preview_size()

        if not poster_url:
            self.clear_poster_preview("Paste a poster link to preview it here.")
            self.poster_preview_loading_url = None
            return

        if not is_allowed_remote_image_url(poster_url):
            self.clear_poster_preview("Only http and https image links are allowed.")
            self.poster_preview_loading_url = None
            return

        cached_bytes = self.actor_preview_cache.get(poster_url)
        if cached_bytes:
            if (
                poster_url == self.poster_preview_rendered_url
                and self.poster_preview_rendered_size == preview_size
                and self.poster_preview_image is not None
            ):
                self.poster_preview_status.configure(text="Poster ready.")
                return
            prepared = self.prepare_poster_image(cached_bytes, preview_size)
            if prepared is not None:
                self.poster_preview_rendered_url = poster_url
                self.poster_preview_rendered_size = preview_size
                self.show_poster_preview_image(prepared)
                return
            self.actor_preview_cache.pop(poster_url, None)

        if self.poster_preview_loading_url == poster_url:
            if self.poster_preview_image is None:
                self.poster_preview_status.configure(text="Loading poster preview...")
            return
        self.poster_preview_loading_url = poster_url
        self.clear_poster_preview("Loading poster preview...")

        def worker():
            image_bytes = self.fetch_actor_thumb(poster_url)
            self.root.after(0, lambda: self.finish_poster_preview(poster_url, image_bytes))

        Thread(target=worker, daemon=True).start()

    def finish_poster_preview(self, poster_url, image_bytes):
        self.poster_preview_loading_url = None
        if poster_url != self.poster_preview_request_url:
            return
        preview_size = self.get_poster_preview_size()

        if image_bytes is None:
            self.actor_preview_cache.pop(poster_url, None)
            self.clear_poster_preview("Could not load a valid image preview.")
            return

        prepared = self.prepare_poster_image(image_bytes, preview_size)
        if prepared is None:
            self.actor_preview_cache.pop(poster_url, None)
            self.clear_poster_preview("Poster link did not return a valid image.")
            return
        self.actor_preview_cache[poster_url] = image_bytes
        self.poster_preview_rendered_url = poster_url
        self.poster_preview_rendered_size = preview_size
        self.show_poster_preview_image(prepared)

    def save_poster_png(self):
        pending_downloads = self.collect_png_targets(os.path.dirname(self.current_file) if self.current_file else "")
        if pending_downloads is None:
            return
        if not pending_downloads:
            messagebox.showerror("Missing Images", "Enter a Poster Link or one or more Backdrop Links first.")
            return
        if self.current_file:
            target_dir = os.path.dirname(self.current_file)
        else:
            target_dir = filedialog.askdirectory(title="Choose folder for poster and backdrop PNGs")
            if not target_dir:
                return
            pending_downloads = self.collect_png_targets(target_dir)
            if pending_downloads is None or not pending_downloads:
                return

        existing_paths = []
        for _image_url, path in pending_downloads:
            if os.path.exists(path):
                existing_paths.append(path)
        if existing_paths and not self.confirm_overwrite_paths(existing_paths, title="Overwrite PNG Files?"):
            self.set_status("Save Images cancelled", "warning")
            return

        saved_paths = self.save_png_downloads(pending_downloads)
        if saved_paths is None:
            return

        if not saved_paths:
            return

        self.set_status(f"Saved {len(saved_paths)} image file(s) to {target_dir}", "success")
        self.show_saved_png_dialog(saved_paths, target_dir)

    def show_saved_png_dialog(self, saved_paths, target_dir):
        poster_paths = []
        backdrop_paths = []
        other_paths = []
        for path in saved_paths:
            name = os.path.basename(path).lower()
            if "-poster" in name:
                poster_paths.append(path)
            elif "-backdrop" in name:
                backdrop_paths.append(path)
            else:
                other_paths.append(path)

        sections = []
        if poster_paths:
            sections.append(("Poster", poster_paths))
        if backdrop_paths:
            sections.append(("Backdrops", backdrop_paths))
        if other_paths:
            sections.append(("Other Files", other_paths))

        self.show_result_paths_dialog(
            title="Images Saved",
            hero_title="Image export completed",
            hero_body=f"{len(saved_paths)} file(s) saved to {target_dir}",
            sections=sections,
            copy_label="Copy Paths",
            status_message=f"Copied {len(saved_paths)} saved image path(s)",
        )

    def confirm_overwrite_path(self, path, title="Overwrite File?"):
        return messagebox.askyesno(
            title,
            f"This file already exists:\n{path}\n\nDo you want to overwrite it?",
        )

    def confirm_overwrite_paths(self, paths, title="Overwrite Files?"):
        unique_paths = []
        seen = set()
        for path in paths:
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_paths.append(path)

        if not unique_paths:
            return True
        if len(unique_paths) == 1:
            return self.confirm_overwrite_path(unique_paths[0], title=title)

        preview_paths = unique_paths[:5]
        preview_text = "\n".join(preview_paths)
        remaining_count = len(unique_paths) - len(preview_paths)
        if remaining_count > 0:
            preview_text += f"\n... and {remaining_count} more"

        return messagebox.askyesno(
            title,
            f"{len(unique_paths)} files already exist and will be overwritten:\n\n{preview_text}\n\nDo you want to continue?",
        )

    def confirm_use_existing_folder(self, path):
        return messagebox.askyesno(
            "Folder Already Exists",
            f"This folder already exists:\n{path}\n\nDo you want to use this existing folder?",
        )

    def show_result_paths_dialog(self, title, hero_title, hero_body, sections, copy_label="Copy Paths", status_message="Paths copied"):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        win.geometry("700x420")
        win.minsize(560, 320)

        outer = tk.Frame(win, bg=self.colors["page_bg"], padx=14, pady=14)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        hero = tk.Frame(
            outer,
            bg=self.colors["success_soft"],
            highlightthickness=1,
            highlightbackground=self.colors["border_soft"],
            padx=14,
            pady=12,
        )
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        hero.grid_columnconfigure(0, weight=1)

        tk.Label(
            hero,
            text=hero_title,
            bg=self.colors["success_soft"],
            fg=self.colors["success"],
            font=("Segoe UI Semibold", 12),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            hero,
            text=hero_body,
            bg=self.colors["success_soft"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        list_shell = tk.Frame(
            outer,
            bg=self.colors["border_soft"],
            padx=1,
            pady=1,
            highlightthickness=0,
            bd=0,
        )
        list_shell.grid(row=1, column=0, sticky="nsew")
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)

        list_body = tk.Frame(list_shell, bg=self.colors["surface"])
        list_body.grid(row=0, column=0, sticky="nsew")
        list_body.grid_columnconfigure(0, weight=1)
        list_body.grid_rowconfigure(0, weight=1)

        list_text = tk.Text(
            list_body,
            font=("Consolas", 9),
            bg=self.colors["surface"],
            fg=self.colors["text"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="none",
            padx=10,
            pady=10,
        )
        list_text.grid(row=0, column=0, sticky="nsew")
        for section_title, paths in sections:
            list_text.insert(tk.END, f"{section_title}\n")
            for path in paths:
                list_text.insert(tk.END, f"  {path}\n")
            list_text.insert(tk.END, "\n")
        list_text.configure(state="disabled")

        scrollbar = ttk.Scrollbar(list_body, orient="vertical", command=list_text.yview, style="Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns")
        list_text.configure(yscrollcommand=scrollbar.set)

        button_row = tk.Frame(outer, bg=self.colors["page_bg"])
        button_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        def copy_all_paths():
            combined = "\n".join(path for _section_title, paths in sections for path in paths)
            self.root.clipboard_clear()
            self.root.clipboard_append(combined)
            self.root.update()
            self.set_status(status_message, "success")

        ttk.Button(button_row, text=copy_label, style="App.TButton", command=copy_all_paths).pack(side="left")
        ttk.Button(button_row, text="Close", style="Primary.TButton", command=win.destroy).pack(side="right")

    def build_actor_values(self, item=None):
        name = self.actor_entries["Name"].get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Actor name is required.")
            self.actor_entries["Name"].focus_set()
            return None

        sort_val = self.actor_entries["SortOrder"].get().strip()
        if not sort_val.isdigit():
            sort_val = str(self.get_next_sort_order(exclude_item=item))

        return (
            name,
            self.actor_entries["Role"].get().strip(),
            "Actor",
            sort_val,
            self.actor_entries["Thumb"].get().strip(),
        )

    def add_actor(self):
        vals = self.build_actor_values()
        if not vals:
            return

        self.actor_data.append(vals)
        self.refresh_actor_list()
        new_index = len(self.actor_data) - 1
        self.select_actor(new_index)
        self.set_status(f"Actor added: {vals[0]}", "success")

    def save_actor(self):
        if self.selected_actor_index is None:
            messagebox.showinfo("No Actor Selected", "Select an actor to update, or use Add Actor for a new one.")
            return

        vals = self.build_actor_values(item=self.selected_actor_index)
        if not vals:
            return

        self.actor_data[self.selected_actor_index] = vals
        self.refresh_actor_list()
        self.select_actor(self.selected_actor_index)
        self.set_status(f"Actor updated: {vals[0]}", "success")

    def create_buttons(self, parent):
        bar = tk.Frame(parent, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        frame = ttk.Frame(bar, padding=(10, 8, 10, 8), style="Card.TFrame")
        frame.pack(fill="x", expand=True)

        web_group = ttk.Frame(frame, style="Card.TFrame")
        web_group.pack(side="left")
        ttk.Button(web_group, text="Open JAVDB", style="Primary.TButton", command=self.open_javdatabase_page).pack(side="left")

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y", padx=10)

        file_group = ttk.Frame(frame, style="Card.TFrame")
        file_group.pack(side="left")
        ttk.Button(file_group, text="Load", style="App.TButton", command=self.load_nfo_dialog).pack(side="left", padx=(0, 5))
        ttk.Button(file_group, text="Save", style="App.TButton", command=self.save_nfo).pack(side="left", padx=5)
        ttk.Button(file_group, text="Save As", style="App.TButton", command=self.save_as_nfo).pack(side="left", padx=5)
        ttk.Button(file_group, text="Create Movie", style="Primary.TButton", command=self.create_movie).pack(side="left", padx=(8, 0))

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y", padx=10)

        clear_group = ttk.Frame(frame, style="Card.TFrame")
        clear_group.pack(side="left")
        ttk.Button(clear_group, text="Clear Info", style="App.TButton", command=self.clear_info).pack(side="left", padx=(0, 5))
        ttk.Button(clear_group, text="Clear All", style="App.TButton", command=self.clear_fields).pack(side="left", padx=(5, 0))

    def create_menu_bar(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load", command=self.load_nfo_dialog)
        file_menu.add_command(label="Save", command=self.save_nfo)
        file_menu.add_command(label="Save As", command=self.save_as_nfo)
        file_menu.add_command(label="Create Folder", command=self.create_folder)
        file_menu.add_command(label="Save Images", command=self.save_poster_png)
        file_menu.add_command(label="Create Movie", command=self.create_movie)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Tag Settings", command=self.open_tag_settings)
        settings_menu.add_command(label="Website Settings", command=self.open_website_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        self.root.config(menu=menubar)

    def create_preview_bar(self, parent):
        bar = tk.Frame(parent, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        frame = ttk.Frame(bar, padding=(10, 8, 10, 8), style="Card.TFrame")
        frame.pack(fill="x", expand=True)
        frame.columnconfigure(1, weight=1)

        meta = tk.Frame(frame, bg=self.colors["surface"])
        meta.grid(row=0, column=0, sticky="w", padx=(0, 12))
        tk.Label(
            meta,
            text="Naming Preview",
            bg=self.colors["accent_soft"],
            fg=self.colors["accent"],
            padx=10,
            pady=5,
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")

        content = tk.Frame(frame, bg=self.colors["surface"])
        content.grid(row=0, column=1, sticky="ew")
        content.columnconfigure(0, weight=1)

        self.naming_preview_var = tk.StringVar()
        ttk.Label(
            content,
            textvariable=self.naming_preview_var,
            style="Card.TLabel",
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        ttk.Button(
            frame,
            text="Copy Filename",
            style="App.TButton",
            command=self.copy_filename_stem,
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.update_name_preview()

    def create_status_bar(self, parent):
        self.status_var = tk.StringVar(value="No file loaded")
        bar = tk.Frame(parent, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        bar.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))

        shell = tk.Frame(bar, bg=self.colors["surface"], padx=10, pady=8)
        shell.pack(fill="x", expand=True)
        shell.grid_columnconfigure(1, weight=1)

        self.status_badge = tk.Label(
            shell,
            text="Info",
            bg=self.colors["accent_soft"],
            fg=self.colors["accent"],
            padx=10,
            pady=4,
            font=("Segoe UI Semibold", 8),
        )
        self.status_badge.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.status_label = tk.Label(
            shell,
            textvariable=self.status_var,
            bg=self.colors["surface"],
            fg=self.colors["text"],
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        )
        self.status_label.grid(row=0, column=1, sticky="ew")
        self.set_status("No file loaded", "neutral")

    def toggle_section(self, section_key):
        section = self.collapsible_sections.get(section_key)
        if not section:
            return
        collapsed = not section["collapsed"]
        section["collapsed"] = collapsed
        if collapsed:
            section["body"].grid_remove()
            section["button"].configure(text="+")
        else:
            section["body"].grid()
            section["button"].configure(text="-")
        if hasattr(self, "form_canvas"):
            self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all"))
        if hasattr(self, "poster_canvas"):
            self.poster_canvas.configure(scrollregion=self.poster_canvas.bbox("all"))

    def create_card_section(self, parent, title, row, sticky="ew", pady=(0, 6), collapsed=False):
        card = tk.Frame(
            parent,
            bg=self.colors["border_soft"],
            bd=0,
            highlightthickness=0,
            padx=1,
            pady=1,
        )
        card.grid(row=row, column=0, sticky=sticky, pady=pady)
        if "n" in sticky or "s" in sticky:
            card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        shell = tk.Frame(card, bg=self.colors["surface"], padx=0, pady=0)
        shell.grid(row=0, column=0, sticky=sticky)
        shell.grid_columnconfigure(0, weight=1)
        if "n" in sticky or "s" in sticky:
            shell.grid_rowconfigure(1, weight=1)

        header = tk.Frame(shell, bg=self.colors["header_bg"], padx=12, pady=10)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        clean_title = title.strip()
        ttk.Label(header, text=clean_title, style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        toggle_button = tk.Button(
            header,
            text="+" if collapsed else "-",
            command=lambda key=clean_title: self.toggle_section(key),
            bg=self.colors["header_bg"],
            fg=self.colors["muted"],
            activebackground=self.colors["surface_alt"],
            activeforeground=self.colors["text"],
            relief="flat",
            bd=0,
            padx=6,
            pady=0,
            font=("Segoe UI Semibold", 12),
            cursor="hand2",
        )
        toggle_button.grid(row=0, column=1, sticky="e")

        body = tk.Frame(shell, bg=self.colors["surface"], padx=12, pady=10)
        body.grid(row=1, column=0, sticky=sticky)
        section = ttk.Frame(body, style="Card.TFrame")
        section.grid(row=0, column=0, sticky=sticky)
        body.grid_columnconfigure(0, weight=1)
        self.collapsible_sections[clean_title] = {
            "body": body,
            "button": toggle_button,
            "collapsed": collapsed,
        }
        if collapsed:
            body.grid_remove()
        return card, section

    def set_status(self, message, tone="neutral"):
        tone_styles = {
            "neutral": ("Info", self.colors["accent_soft"], self.colors["accent"], self.colors["text"]),
            "success": ("Saved", self.colors["success_soft"], self.colors["success"], self.colors["text"]),
            "error": ("Error", self.colors["danger_soft"], self.colors["danger"], self.colors["danger"]),
            "warning": ("Note", self.colors["warning_soft"], self.colors["warning"], self.colors["text"]),
        }
        badge_text, badge_bg, badge_fg, text_fg = tone_styles.get(tone, tone_styles["neutral"])
        self.status_var.set(message)
        if hasattr(self, "status_badge"):
            self.status_badge.configure(text=badge_text, bg=badge_bg, fg=badge_fg)
        if hasattr(self, "status_label"):
            self.status_label.configure(fg=text_fg)

    def get_poster_preview_size(self):
        if not hasattr(self, "poster_preview_frame") or not self.poster_preview_frame.winfo_exists():
            return (340, 480)
        self.poster_preview_frame.update_idletasks()
        available_width = max(340, self.poster_preview_frame.winfo_width() - 20)
        available_height = max(480, int(available_width * 1.42))
        return (available_width, available_height)

    def get_poster_placeholder_image(self, size=None):
        return self.get_actor_placeholder_image("Poster", size=size or self.get_poster_preview_size())

    def get_next_sort_order(self, exclude_item=None):
        used = []
        for index, values in enumerate(self.actor_data):
            if index == exclude_item:
                continue
            try:
                used.append(int(values[3]))
            except (TypeError, ValueError, IndexError):
                pass

        next_value = 0
        while next_value in used:
            next_value += 1
        return next_value

    def strip_tag_from_title(self, title):
        return remove_supported_tags(title, self.supported_tags)

    def detect_tag_from_text(self, text):
        return detect_supported_tag(text, self.supported_tags)

    def detect_tag_for_loaded_movie(self, path, title):
        tag = self.detect_tag_from_text(os.path.basename(path))
        if tag:
            return tag
        return self.detect_tag_from_text(title)

    def load_nfo_dialog(self):
        path = filedialog.askopenfilename(filetypes=[("NFO/XML", "*.nfo *.xml")])
        if path:
            self.load_nfo(path)

    def set_current_file(self, path=None):
        self.current_file = path
        if path:
            self.set_status(f"Loaded: {path}", "neutral")
        else:
            self.set_status("No file loaded", "neutral")

    def reset_country_default(self):
        self.entries["Country"].delete(0, tk.END)
        self.entries["Country"].insert(0, DEFAULT_COUNTRY)
        self.update_name_preview()

    def bind_preview_updates(self):
        for key in ("Title", "OriginalTitle", "Premiered"):
            self.entries[key].bind("<KeyRelease>", lambda event: self.update_name_preview(), add="+")
            self.entries[key].bind("<FocusOut>", lambda event: self.update_name_preview(), add="+")
        self.tag_var.trace_add("write", lambda *_args: self.update_name_preview())

    def refresh_tag_values(self):
        normalized_current = normalize_supported_tag(self.tag_var.get(), self.supported_tags)
        self.tag_combo["values"] = ["", *self.supported_tags]
        self.tag_var.set(normalized_current if normalized_current in self.supported_tags else "")

    def open_tag_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Tag Settings")
        win.transient(self.root)
        win.grab_set()
        win.geometry("420x360")
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text="Manage Tags", style="App.TLabel").grid(row=0, column=0, sticky="w")

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        tag_list = tk.Listbox(list_frame, activestyle="none", font=("Segoe UI", 10), height=10)
        tag_list.grid(row=0, column=0, sticky="nsew")
        working_tags = list(self.supported_tags)
        for tag in working_tags:
            tag_list.insert(tk.END, tag)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=tag_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tag_list.configure(yscrollcommand=scrollbar.set)

        entry_frame = ttk.Frame(frame)
        entry_frame.grid(row=2, column=0, sticky="ew")
        entry_frame.columnconfigure(0, weight=1)

        new_tag_var = tk.StringVar()
        entry = ttk.Entry(entry_frame, textvariable=new_tag_var)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        def add_tag():
            raw_tag = new_tag_var.get().strip()
            if not raw_tag:
                return
            if raw_tag.casefold() in {tag.casefold() for tag in working_tags}:
                messagebox.showinfo("Tag Exists", f"That tag already exists:\n{raw_tag}", parent=win)
                return
            working_tags.append(raw_tag)
            tag_list.insert(tk.END, raw_tag)
            new_tag_var.set("")

        def remove_selected_tag():
            selection = tag_list.curselection()
            if not selection:
                return
            index = selection[0]
            del working_tags[index]
            tag_list.delete(index)

        ttk.Button(entry_frame, text="Add", style="App.TButton", command=add_tag).grid(row=0, column=1)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(button_frame, text="Remove Selected", style="App.TButton", command=remove_selected_tag).pack(side="left")

        def save_and_close():
            if not working_tags:
                messagebox.showerror("Missing Tags", "At least one tag is required.", parent=win)
                return
            self.supported_tags = list(working_tags)
            save_configured_tags(self.supported_tags)
            self.refresh_tag_values()
            self.set_status("Tag settings saved", "success")
            win.destroy()

        ttk.Button(button_frame, text="Save", style="App.TButton", command=save_and_close).pack(side="right")
        ttk.Button(button_frame, text="Cancel", style="App.TButton", command=win.destroy).pack(side="right", padx=(0, 8))

        entry.bind("<Return>", lambda _event: add_tag())
        self.bind_descendant_edit_widgets(win)
        entry.focus_set()

    def open_website_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Website Settings")
        win.transient(self.root)
        win.grab_set()
        win.geometry("500x210")
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Open JAVDB URL Template", style="App.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame,
            text="Use {title} where the movie code should go.",
            style="App.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))

        template_var = tk.StringVar(value=self.javdb_url_template)
        entry = ttk.Entry(frame, textvariable=template_var)
        entry.grid(row=2, column=0, sticky="ew")

        example_label = ttk.Label(frame, style="App.TLabel")
        example_label.grid(row=3, column=0, sticky="w", pady=(8, 0))

        def update_example(*_args):
            example = build_javdb_url(template_var.get() or DEFAULT_JAVDB_URL_TEMPLATE, "SQTE-515")
            example_label.configure(text=f"Example: {example}")

        def save_and_close():
            template = template_var.get().strip()
            if "{title}" not in template:
                messagebox.showerror("Invalid Template", "The URL template must include {title}.", parent=win)
                return
            self.javdb_url_template = template
            save_javdb_url_template(template)
            self.set_status("Website settings saved", "success")
            win.destroy()

        template_var.trace_add("write", update_example)
        update_example()

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(button_frame, text="Reset", style="App.TButton", command=lambda: template_var.set(DEFAULT_JAVDB_URL_TEMPLATE)).pack(
            side="left"
        )
        ttk.Button(button_frame, text="Save", style="App.TButton", command=save_and_close).pack(side="right")
        ttk.Button(button_frame, text="Cancel", style="App.TButton", command=win.destroy).pack(side="right", padx=(0, 8))

        self.bind_descendant_edit_widgets(win)
        entry.focus_set()

    def update_name_preview(self):
        if not getattr(self, "naming_preview_var", None):
            return

        title = self.get_field_value("Title")
        year = extract_year(self.get_field_value("Premiered"))
        original = self.get_field_value("OriginalTitle")
        tag = self.tag_var.get()

        filename = f"{build_movie_name(title, year, tag)}.nfo"
        folder_name = build_movie_name(title, year, tag, original)
        self.naming_preview_var.set(f"{filename} | {folder_name}")

    def copy_filename_stem(self):
        title = self.get_field_value("Title")
        year = extract_year(self.get_field_value("Premiered"))
        tag = self.tag_var.get()
        filename_stem = build_movie_name(title, year, tag)
        self.root.clipboard_clear()
        self.root.clipboard_append(filename_stem)
        self.root.update()
        self.set_status(f"Copied filename: {filename_stem}", "success")

    def get_field_value(self, key):
        if key in self.text_fields:
            return self.text_fields[key].get("1.0", tk.END).strip()
        return self.entries[key].get().strip()

    def get_poster_field_value(self, key):
        if key in self.poster_text_fields:
            return self.poster_text_fields[key].get("1.0", tk.END).strip()
        return ""

    def set_field_value(self, key, value):
        if key in self.text_fields:
            self.text_fields[key].delete("1.0", tk.END)
            self.text_fields[key].insert("1.0", value)
            self.update_name_preview()
            return
        self.entries[key].delete(0, tk.END)
        self.entries[key].insert(0, value)
        self.update_name_preview()

    def clear_field_value(self, key):
        self.set_field_value(key, "")

    def clear_poster_field_value(self, key):
        if key in self.poster_text_fields:
            self.poster_text_fields[key].delete("1.0", tk.END)

    def load_nfo(self, path):
        try:
            tree = parse_xml_file(path)
        except (ET.ParseError, OSError) as exc:
            messagebox.showerror("Load Failed", f"Could not open file:\n{path}\n\n{exc}")
            return

        root = tree.getroot()
        title_text = root.findtext("title", "") or ""

        for key in self.entries:
            if key == "Genre":
                val = format_loaded_genres(root)
            else:
                val = root.findtext(key.lower(), "") or ""
            if key == "Title":
                val = self.strip_tag_from_title(val)
            self.set_field_value(key, val)

        self.set_field_value("Plot", root.findtext("plot", "") or "")

        self.actor_data = []
        for index, actor in enumerate(root.findall("actor")):
            self.actor_data.append(
                (
                    actor.findtext("name", ""),
                    actor.findtext("role", ""),
                    actor.findtext("type", "Actor"),
                    actor_sortorder_for_display(actor, index),
                    actor.findtext("thumb", ""),
                )
            )
        self.refresh_actor_list()
        self.poster_link_var.set("")
        self.clear_poster_field_value("BackdropLinks")

        self.tag_var.set(self.detect_tag_for_loaded_movie(path, title_text))
        self.set_current_file(path)
        self.clear_actor_editor()

    def open_javdatabase_page(self):
        movie_code = self.get_field_value("Title").strip()
        if not movie_code:
            messagebox.showerror("Missing Title", "Enter the movie code in Title first.")
            return

        url = build_javdb_url(self.javdb_url_template, movie_code)
        opened = webbrowser.open(url)
        if not opened:
            messagebox.showerror("Open Failed", f"Could not open browser for:\n{url}")
            return
        self.set_status(f"Opened JAVDB: {movie_code}", "neutral")

    def build_xml(self):
        movie = ET.Element("movie")
        tag = self.tag_var.get().strip()
        values_by_key = {}

        for field_key, _xml_tag in MOVIE_XML_ORDER:
            if field_key == "MPAA":
                val = "XXX"
            else:
                val = self.get_field_value(field_key)
            if field_key == "Title" and val:
                val = val.upper()
                if tag and not contains_supported_tag(val, tag, self.supported_tags):
                    val = f"{val} {tag}"
            if field_key == "OriginalTitle" and val:
                val = proper_case(val)
            values_by_key[field_key] = val

        for field_key, xml_tag in MOVIE_XML_ORDER:
            if field_key == "Set":
                continue
            val = values_by_key[field_key]
            if val:
                if field_key == "Genre":
                    for genre_value in parse_genre_values(val):
                        ET.SubElement(movie, xml_tag).text = genre_value
                else:
                    ET.SubElement(movie, xml_tag).text = val

        premiered_year = extract_year(values_by_key["Premiered"])
        if premiered_year:
            ET.SubElement(movie, "year").text = premiered_year

        for vals in self.actor_data:
            if not any(vals):
                continue

            actor = ET.SubElement(movie, "actor")
            for tag_name, value in zip(ACTOR_XML_FIELDS, vals):
                if value:
                    ET.SubElement(actor, tag_name).text = value

        set_value = values_by_key["Set"]
        if set_value:
            ET.SubElement(movie, "set").text = set_value

        indent_xml(movie)
        return movie

    def save_nfo(self):
        if not self.current_file:
            self.save_as_nfo()
            return

        if os.path.exists(self.current_file) and not self.confirm_overwrite_path(self.current_file):
            self.set_status("Save cancelled", "warning")
            return

        try:
            write_xml_file(self.build_xml(), self.current_file)
        except OSError as exc:
            messagebox.showerror("Save Failed", f"Could not save file:\n{self.current_file}\n\n{exc}")
            return

        messagebox.showinfo("Saved", "Movie saved")
        self.set_status(f"Saved: {self.current_file}", "success")

    def save_as_nfo(self):
        dialog_kwargs = {
            "initialfile": self.build_filename(),
            "defaultextension": ".nfo",
        }
        if self.current_file:
            dialog_kwargs["initialdir"] = os.path.dirname(self.current_file)

        path = filedialog.asksaveasfilename(**dialog_kwargs)
        if not path:
            return

        if os.path.exists(path) and not self.confirm_overwrite_path(path):
            self.set_status("Save As cancelled", "warning")
            return

        try:
            write_xml_file(self.build_xml(), path)
        except OSError as exc:
            messagebox.showerror("Save Failed", f"Could not save file:\n{path}\n\n{exc}")
            return

        self.set_current_file(path)
        self.set_status(f"Saved: {path}", "success")
        self.show_result_paths_dialog(
            title="File Saved",
            hero_title="NFO file saved",
            hero_body=f"Metadata file saved successfully to {os.path.dirname(path)}",
            sections=[("Saved File", [path])],
            copy_label="Copy Path",
            status_message="Copied saved file path",
        )

    def build_filename(self):
        year_value = extract_year(self.get_field_value("Premiered"))
        return f"{build_movie_name(self.get_field_value('Title'), year_value, self.tag_var.get())}.nfo"

    def build_movie_folder_name(self):
        return build_movie_name(
            self.get_field_value("Title"),
            extract_year(self.get_field_value("Premiered")),
            self.tag_var.get(),
            self.get_field_value("OriginalTitle"),
        )

    def validate_title_and_year(self, action_label):
        title = self.get_field_value("Title").strip()
        year = extract_year(self.get_field_value("Premiered"))
        if not title or not year:
            messagebox.showerror("Missing Information", f"Title and Year are required before {action_label}.")
            return None
        return title, year

    def choose_movie_file_path(self, title="Choose movie file"):
        dialog_kwargs = {
            "title": title,
            "filetypes": [
                ("Video Files", "*.mp4 *.mkv *.avi *.wmv *.mov *.m4v *.ts *.m2ts *.webm"),
                ("All Files", "*.*"),
            ],
        }
        if self.current_video_file and os.path.exists(self.current_video_file):
            dialog_kwargs["initialdir"] = os.path.dirname(self.current_video_file)
        elif self.current_file:
            dialog_kwargs["initialdir"] = os.path.dirname(self.current_file)
        return filedialog.askopenfilename(**dialog_kwargs)

    def choose_movie_file_paths(self, title="Choose movie files"):
        dialog_kwargs = {
            "title": title,
            "filetypes": [
                ("Video Files", "*.mp4 *.mkv *.avi *.wmv *.mov *.m4v *.ts *.m2ts *.webm"),
                ("All Files", "*.*"),
            ],
        }
        if self.current_video_file and os.path.exists(self.current_video_file):
            dialog_kwargs["initialdir"] = os.path.dirname(self.current_video_file)
        elif self.current_file:
            dialog_kwargs["initialdir"] = os.path.dirname(self.current_file)
        return list(filedialog.askopenfilenames(**dialog_kwargs))

    def collect_png_targets(self, target_dir, base_filename=None):
        poster_url = self.poster_link_var.get().strip()
        backdrop_links = parse_multiline_links(self.poster_text_fields["BackdropLinks"].get("1.0", tk.END))
        if not poster_url and not backdrop_links:
            return []

        invalid_links = [url for url in [poster_url, *backdrop_links] if url and not is_allowed_remote_image_url(url)]
        if invalid_links:
            messagebox.showerror("Invalid Image Link", "Only http and https image links are allowed.")
            return None

        base_filename = base_filename or self.build_filename()
        pending_downloads = []
        if poster_url:
            pending_downloads.append((poster_url, os.path.join(target_dir, build_poster_png_name(base_filename))))
        for link, filename in zip(backdrop_links, build_backdrop_png_names(base_filename, len(backdrop_links))):
            pending_downloads.append((link, os.path.join(target_dir, filename)))
        return pending_downloads

    def save_png_downloads(self, pending_downloads):
        saved_paths = []
        for image_url, path in pending_downloads:
            image_bytes = self.actor_preview_cache.get(image_url)
            if image_bytes is None:
                image_bytes = self.fetch_actor_thumb(image_url)
                if image_bytes is None:
                    messagebox.showerror("Download Failed", f"Could not download a valid image from:\n{image_url}")
                    return None

            try:
                self.save_image_bytes_as_png(image_bytes, path)
                self.actor_preview_cache[image_url] = image_bytes
            except Exception as exc:
                self.actor_preview_cache.pop(image_url, None)
                messagebox.showerror("Save Failed", f"Could not save a valid PNG:\n{path}\n\n{exc}")
                return None
            saved_paths.append(path)
        return saved_paths

    def load_video_file(self):
        if not self.validate_title_and_year("choosing a movie file"):
            return

        source_path = self.choose_movie_file_path(title="Choose video file to rename")
        if not source_path:
            return

        target_name = build_matching_video_filename(source_path, self.build_filename())
        target_path = os.path.join(os.path.dirname(source_path), target_name)

        if os.path.normcase(source_path) == os.path.normcase(target_path):
            self.set_status(f"Video already matches filename: {target_name}", "neutral")
            self.show_result_paths_dialog(
                title="Video Already Matches",
                hero_title="Video already renamed",
                hero_body="The selected video file already matches the current NFO filename.",
                sections=[("Video File", [target_path])],
                copy_label="Copy Path",
                status_message="Copied video file path",
            )
            self.current_video_file = target_path
            return

        if os.path.exists(target_path):
            messagebox.showerror(
                "Rename Video Failed",
                f"A file with the target name already exists:\n{target_path}",
            )
            return

        if os.path.exists(target_path) and not self.confirm_overwrite_path(target_path, title="Overwrite Movie File?"):
            self.set_status("Movie rename cancelled", "warning")
            return

        try:
            os.replace(source_path, target_path)
        except OSError as exc:
            messagebox.showerror(
                "Rename Video Failed",
                f"Could not rename video file:\n{source_path}\n\nTarget:\n{target_path}\n\n{exc}",
            )
            return

        self.current_video_file = target_path
        self.set_status(f"Video renamed: {target_path}", "success")
        self.show_result_paths_dialog(
            title="Video Renamed",
            hero_title="Video file renamed",
            hero_body=f"Video renamed to match the current NFO filename in {os.path.dirname(target_path)}",
            sections=[("Renamed Video", [target_path])],
            copy_label="Copy Path",
            status_message="Copied renamed video path",
        )

    def create_movie(self):
        if not self.validate_title_and_year("creating a movie"):
            return

        base = filedialog.askdirectory(title="Choose base folder for the movie")
        if not base:
            return

        folder_path = os.path.join(base, self.build_movie_folder_name())
        if os.path.isdir(folder_path):
            if not self.confirm_use_existing_folder(folder_path):
                self.set_status("Create Movie cancelled", "warning")
                return

        video_sources = self.choose_movie_file_paths(title="Choose movie file(s) to move into the movie folder (optional)")
        base_nfo_filename = self.build_filename()
        file_plans = []

        if video_sources:
            for index, video_source in enumerate(video_sources, start=1):
                nfo_filename = base_nfo_filename
                if len(video_sources) > 1:
                    nfo_filename = build_part_filename(base_nfo_filename, index)
                include_metadata = len(video_sources) == 1 or index == 1
                nfo_path = os.path.join(folder_path, nfo_filename) if include_metadata else None
                video_target = os.path.join(folder_path, build_matching_video_filename(video_source, nfo_filename))
                png_targets = []
                if include_metadata:
                    png_targets = self.collect_png_targets(folder_path, base_filename=nfo_filename)
                    if png_targets is None:
                        return
                file_plans.append(
                    {
                        "index": index,
                        "include_metadata": include_metadata,
                        "video_source": video_source,
                        "nfo_filename": nfo_filename,
                        "nfo_path": nfo_path,
                        "video_target": video_target,
                        "png_targets": png_targets,
                    }
                )
        else:
            nfo_path = os.path.join(folder_path, base_nfo_filename)
            png_targets = self.collect_png_targets(folder_path, base_filename=base_nfo_filename)
            if png_targets is None:
                return
            file_plans.append(
                {
                    "index": 1,
                    "include_metadata": True,
                    "video_source": "",
                    "nfo_filename": base_nfo_filename,
                    "nfo_path": nfo_path,
                    "video_target": None,
                    "png_targets": png_targets,
                }
            )

        existing_paths = []
        for plan in file_plans:
            if plan["nfo_path"] and os.path.exists(plan["nfo_path"]):
                existing_paths.append(plan["nfo_path"])
            for _image_url, path in plan["png_targets"]:
                if os.path.exists(path):
                    existing_paths.append(path)
            video_source = plan["video_source"]
            video_target = plan["video_target"]
            if (
                video_source
                and video_target
                and os.path.exists(video_target)
                and os.path.normcase(os.path.abspath(video_source)) != os.path.normcase(os.path.abspath(video_target))
            ):
                existing_paths.append(video_target)

        if existing_paths and not self.confirm_overwrite_paths(existing_paths, title="Overwrite Movie Files?"):
            self.set_status("Create Movie cancelled", "warning")
            return

        try:
            os.makedirs(folder_path, exist_ok=True)
            movie_xml = self.build_xml()
            for plan in file_plans:
                if plan["nfo_path"]:
                    write_xml_file(movie_xml, plan["nfo_path"])
        except OSError as exc:
            messagebox.showerror("Create Movie Failed", f"Could not create movie folder or save NFO:\n{folder_path}\n\n{exc}")
            return

        saved_pngs = []
        for plan in file_plans:
            plan_saved_pngs = self.save_png_downloads(plan["png_targets"])
            if plan_saved_pngs is None:
                return
            saved_pngs.extend(plan_saved_pngs)

        saved_video_targets = []
        for plan in file_plans:
            video_source = plan["video_source"]
            video_target = plan["video_target"]
            if not video_source or not video_target:
                continue
            try:
                if os.path.normcase(os.path.abspath(video_source)) != os.path.normcase(os.path.abspath(video_target)):
                    if os.path.exists(video_target):
                        os.remove(video_target)
                    shutil.move(video_source, video_target)
            except OSError as exc:
                messagebox.showerror(
                    "Create Movie Failed",
                    f"Could not move movie file:\n{video_source}\n\nTarget:\n{video_target}\n\n{exc}",
                )
                return
            saved_video_targets.append(video_target)

        self.current_video_file = saved_video_targets[0] if saved_video_targets else None
        metadata_plan = next((plan for plan in file_plans if plan["nfo_path"]), None)
        self.set_current_file(metadata_plan["nfo_path"] if metadata_plan else None)
        self.set_status(f"Movie package created: {folder_path}", "success")

        saved_nfo_paths = [plan["nfo_path"] for plan in file_plans if plan["nfo_path"]]
        sections = [("Created Folder", [folder_path])]
        if saved_nfo_paths:
            sections.append(("Saved NFO", saved_nfo_paths))
        if saved_video_targets:
            sections.append(("Movie Files", saved_video_targets))
        if saved_pngs:
            poster_paths = [path for path in saved_pngs if "-poster" in os.path.basename(path).lower()]
            backdrop_paths = [path for path in saved_pngs if "-backdrop" in os.path.basename(path).lower()]
            other_paths = [path for path in saved_pngs if path not in poster_paths and path not in backdrop_paths]
            if poster_paths:
                sections.append(("Poster", poster_paths))
            if backdrop_paths:
                sections.append(("Backdrops", backdrop_paths))
            if other_paths:
                sections.append(("Other Files", other_paths))

        self.show_result_paths_dialog(
            title="Movie Created",
            hero_title="Movie package created",
            hero_body=(
                f"Folder, NFO, images, and movie files saved successfully in {folder_path}"
                if saved_video_targets
                else f"Folder, NFO, and images saved successfully in {folder_path}"
            ),
            sections=sections,
            copy_label="Copy Paths",
            status_message="Copied created movie paths",
        )

    def create_folder(self):
        title = self.get_field_value("Title")
        year = extract_year(self.get_field_value("Premiered"))
        if not title or not year:
            messagebox.showerror("Missing Information", "Title and Year are required to create a folder.")
            return

        name = build_movie_name(
            title,
            year,
            self.tag_var.get(),
            self.get_field_value("OriginalTitle"),
        )

        base = filedialog.askdirectory()
        if not base:
            return

        path = os.path.join(base, name)
        if os.path.isdir(path):
            if not self.confirm_use_existing_folder(path):
                self.set_status("Create Folder cancelled", "warning")
                return
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Create Folder Failed", f"Could not create folder:\n{path}\n\n{exc}")
            return

        self.set_status(f"Folder created: {path}", "success")
        self.show_result_paths_dialog(
            title="Folder Created",
            hero_title="Folder created",
            hero_body=f"Movie folder created successfully in {base}",
            sections=[("Created Folder", [path])],
            copy_label="Copy Folder Path",
            status_message="Copied created folder path",
        )

    def clear_info(self):
        for key in self.entries:
            if key in ("Set", "Genre"):
                continue
            self.clear_field_value(key)

        self.clear_field_value("Plot")

        self.reset_country_default()
        self.tag_var.set("")
        self.poster_link_var.set("")
        self.clear_poster_field_value("BackdropLinks")
        self.current_video_file = None
        self.set_current_file(None)
        self.set_status("Movie info cleared", "warning")
        self.update_name_preview()

    def clear_fields(self):
        for key in self.entries:
            self.clear_field_value(key)

        self.clear_field_value("Plot")

        self.reset_country_default()
        self.tag_var.set("")
        self.poster_link_var.set("")
        self.clear_poster_field_value("BackdropLinks")
        self.current_video_file = None

        self.actor_data = []
        self.refresh_actor_list()

        self.set_current_file(None)
        self.clear_actor_editor()
        self.set_status("All fields cleared", "warning")
        self.update_name_preview()


def run():
    try:
        root = tk.Tk()
        MovieNFOEditor(root)
        root.mainloop()
    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        log_path = log_exception(exc_type, exc_value, exc_traceback)
        try:
            messagebox.showerror(
                "Application Error",
                f"The application hit an unexpected error.\n\nDetails were saved to:\n{log_path}",
            )
        except Exception:
            pass
        raise
