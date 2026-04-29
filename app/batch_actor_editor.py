import os
import tkinter as tk
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

from app.movie_nfo_editor import fetch_remote_image_bytes, indent_xml, is_allowed_remote_image_url, parse_xml_file, write_xml_file


@dataclass
class ActorInfo:
    name: str
    role: str
    thumb: str
    sortorder: str


@dataclass
class NFORecord:
    path: str
    title: str
    actors: list[ActorInfo]


def find_nfo_files(root_dir: str) -> list[str]:
    matches = []
    for current_root, _dirs, files in os.walk(root_dir):
        for name in files:
            if name.lower().endswith((".nfo", ".xml")):
                matches.append(os.path.join(current_root, name))
    return sorted(matches)


def read_nfo_record(path: str) -> NFORecord:
    tree = parse_xml_file(path)
    root = tree.getroot()
    title = root.findtext("title", "") or os.path.basename(path)
    actors = []
    for actor in root.findall("actor"):
        actors.append(
            ActorInfo(
                name=(actor.findtext("name", "") or "").strip(),
                role=(actor.findtext("role", "") or "").strip(),
                thumb=(actor.findtext("thumb", "") or "").strip(),
                sortorder=(actor.findtext("sortorder", "") or "").strip(),
            )
        )
    return NFORecord(path=path, title=title, actors=actors)


def update_actor_fields_by_name_in_tree(
    tree: ET.ElementTree,
    target_name: str,
    new_role: str,
    new_thumb: str,
) -> int:
    normalized_target = target_name.strip().casefold()
    if not normalized_target:
        return 0

    root = tree.getroot()
    updates = 0
    for actor in root.findall("actor"):
        current_name = (actor.findtext("name", "") or "").strip().casefold()
        if current_name != normalized_target:
            continue

        field_values = {
            "role": new_role,
            "thumb": new_thumb,
        }
        for tag_name, value in field_values.items():
            if value == "":
                continue
            node = actor.find(tag_name)
            if node is None:
                node = ET.SubElement(actor, tag_name)
            node.text = value
        updates += 1

    if updates:
        indent_xml(root)
    return updates


def collect_actor_names(records: list[NFORecord]) -> list[str]:
    names = set()
    for record in records:
        for actor in record.actors:
            if actor.name:
                names.add(actor.name)
    return sorted(names, key=str.lower)


def summarize_actor_names(actors: list[ActorInfo], limit: int = 3) -> str:
    parts = []
    for actor in actors[:limit]:
        name = actor.name or "(no name)"
        parts.append(name)
    summary = ", ".join(parts)
    if len(actors) > limit:
        summary += " ..."
    return summary


def role_for_actor_name(actors: list[ActorInfo], target_name: str) -> str:
    normalized_target = target_name.strip().casefold()
    if not normalized_target:
        return ""
    for actor in actors:
        if actor.name.strip().casefold() == normalized_target:
            return actor.role or "(empty)"
    return "-"


class AutoHideScrollbar(ttk.Scrollbar):
    def set(self, first, last):
        first_value = float(first)
        last_value = float(last)
        if first_value <= 0.0 and last_value >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(first, last)


class BatchActorEditor:
    def __init__(self, root: tk.Tk, host=None, configure_window=True):
        self.root = root
        self.host = host or root
        self.configure_window = configure_window
        if self.configure_window:
            self.root.title("Batch Actor Editor")
            self.root.geometry("1240x780")
            self.root.minsize(1040, 640)

        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a folder to scan for NFO files.")
        self.context_var = tk.StringVar(value="Choose an actor name to preview the batch update.")
        self.actor_name_var = tk.StringVar()
        self.records: list[NFORecord] = []
        self.filtered_records: list[NFORecord] = []
        self.actor_placeholder_cache = {}
        self.actor_thumb_cache = {}
        self.actor_thumb_requests = {}
        self.setup_styles()
        self.create_ui()

    def setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.colors = {
            "page_bg": "#eef3f8",
            "shell_bg": "#f6f9fc",
            "surface": "#ffffff",
            "surface_alt": "#f8fbff",
            "surface_soft": "#fbfdff",
            "border": "#d8e2ee",
            "border_soft": "#e6edf5",
            "border_strong": "#c4d3e4",
            "text": "#162033",
            "muted": "#66758c",
            "subtle": "#8b98ac",
            "accent": "#2f6fed",
            "accent_hover": "#275fcb",
            "accent_soft": "#e8f0ff",
            "selected": "#eff5ff",
            "success": "#1f8f5f",
            "success_soft": "#e8f7ef",
            "warning": "#b7791f",
            "warning_soft": "#fff6e5",
            "danger": "#c94b45",
            "danger_soft": "#fdeeed",
        }

        self.root.configure(background=self.colors["page_bg"])

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background=self.colors["page_bg"])
        style.configure("Shell.TFrame", background=self.colors["shell_bg"])
        style.configure("Card.TFrame", background=self.colors["surface"])
        style.configure("Surface.TFrame", background=self.colors["surface_alt"])
        style.configure("App.TLabel", background=self.colors["page_bg"], foreground=self.colors["muted"])
        style.configure("Shell.TLabel", background=self.colors["shell_bg"], foreground=self.colors["muted"])
        style.configure("Card.TLabel", background=self.colors["surface"], foreground=self.colors["text"])
        style.configure("Surface.TLabel", background=self.colors["surface_alt"], foreground=self.colors["text"])
        style.configure(
            "HeroTitle.TLabel",
            background=self.colors["shell_bg"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 15),
        )
        style.configure(
            "HeroBody.TLabel",
            background=self.colors["shell_bg"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "SectionMeta.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["subtle"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Section.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "FieldLabel.TLabel",
            background=self.colors["surface_alt"],
            foreground="#5e79a2",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Body.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "SurfaceBody.TLabel",
            background=self.colors["surface_alt"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "App.TButton",
            padding=(12, 7),
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
            padding=(14, 9),
            font=("Segoe UI Semibold", 11),
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
            "App.TEntry",
            padding=6,
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
            "App.TCombobox",
            padding=5,
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
            "Treeview",
            rowheight=30,
            font=("Segoe UI", 9),
            background=self.colors["surface"],
            fieldbackground=self.colors["surface"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border_soft"],
            lightcolor=self.colors["surface"],
            darkcolor=self.colors["surface"],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI Semibold", 9),
            background=self.colors["surface_alt"],
            foreground=self.colors["muted"],
            bordercolor=self.colors["border_soft"],
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", self.colors["selected"])],
            foreground=[("selected", self.colors["text"])],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#eef4fb")],
            foreground=[("active", self.colors["text"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#d6e0ec",
            troughcolor="#f3f7fb",
            bordercolor="#f3f7fb",
            arrowcolor="#5f7088",
            relief="flat",
            width=12,
        )
        style.map("Vertical.TScrollbar", background=[("active", "#c7d4e5")])

    def create_ui(self):
        self.host.columnconfigure(0, weight=1)
        self.host.rowconfigure(0, weight=1)

        app = ttk.Frame(self.host, padding=(10, 10, 10, 8), style="App.TFrame")
        app.grid(row=0, column=0, sticky="nsew")
        app.columnconfigure(0, weight=1)
        app.rowconfigure(0, weight=1)

        shell = ttk.Frame(app, padding=10, style="Shell.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        hero = ttk.Frame(shell, padding=(8, 6, 8, 8), style="Shell.TFrame")
        hero.grid(row=0, column=0, sticky="ew")
        hero.columnconfigure(1, weight=1)

        ttk.Label(hero, text="Batch Actor Editor", style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 14))

        folder_bar = tk.Frame(
            hero,
            bg=self.colors["border_soft"],
            bd=0,
            highlightthickness=0,
            padx=1,
            pady=1,
        )
        folder_bar.grid(row=0, column=1, sticky="ew")
        folder_bar.grid_columnconfigure(0, weight=1)

        folder_inner = ttk.Frame(folder_bar, padding=(10, 8), style="Card.TFrame")
        folder_inner.grid(row=0, column=0, sticky="ew")
        folder_inner.columnconfigure(1, weight=1)

        ttk.Label(folder_inner, text="Library Folder", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        folder_entry = ttk.Entry(folder_inner, textvariable=self.folder_var, style="App.TEntry")
        folder_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(folder_inner, text="Browse", style="App.TButton", command=self.choose_folder).grid(row=0, column=2, padx=(10, 0))
        ttk.Button(folder_inner, text="Scan", style="Primary.TButton", command=self.scan_folder).grid(row=0, column=3, padx=(10, 0))

        content = ttk.Frame(shell, style="Shell.TFrame")
        content.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)

        left_outer = tk.Frame(content, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_outer.grid_columnconfigure(0, weight=1)
        left_outer.grid_rowconfigure(0, weight=1)

        left = ttk.Frame(left_outer, padding=(12, 12, 12, 10), style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        ttk.Label(left, text="Movie Settings", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")

        form_shell = ttk.Frame(left, padding=(8, 8, 8, 10), style="Surface.TFrame")
        form_shell.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        form_shell.columnconfigure(0, weight=1)
        form_shell.columnconfigure(1, weight=1)
        form_shell.columnconfigure(2, weight=1)

        ttk.Label(form_shell, text="Actor Name", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", padx=(2, 0))
        ttk.Label(form_shell, text="New Role", style="FieldLabel.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(form_shell, text="New Thumb", style="FieldLabel.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.actor_name_combo = ttk.Combobox(
            form_shell,
            textvariable=self.actor_name_var,
            state="readonly",
            style="App.TCombobox",
        )
        self.actor_name_combo.grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 2))

        self.new_role_var = tk.StringVar()
        ttk.Entry(form_shell, textvariable=self.new_role_var, style="App.TEntry").grid(
            row=1, column=1, sticky="ew", padx=(12, 0), pady=(8, 0)
        )

        self.new_thumb_var = tk.StringVar()
        ttk.Entry(form_shell, textvariable=self.new_thumb_var, style="App.TEntry").grid(
            row=1, column=2, sticky="ew", padx=(12, 0), pady=(8, 0)
        )

        file_header = ttk.Frame(left, style="Card.TFrame")
        file_header.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        file_header.columnconfigure(0, weight=1)
        file_header.rowconfigure(1, weight=1)

        ttk.Label(file_header, text="Files", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")

        tree_shell = tk.Frame(file_header, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        tree_shell.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        tree_shell.grid_columnconfigure(0, weight=1)
        tree_shell.grid_rowconfigure(0, weight=1)

        tree_body = ttk.Frame(tree_shell, padding=0, style="Card.TFrame")
        tree_body.grid(row=0, column=0, sticky="nsew")
        tree_body.columnconfigure(0, weight=1)
        tree_body.rowconfigure(0, weight=1)

        columns = ("Title", "Actors", "Role")
        self.tree = ttk.Treeview(tree_body, columns=columns, show="headings", selectmode="extended")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Actors", text="Actors")
        self.tree.heading("Role", text="Role")
        self.tree.column("Title", width=340)
        self.tree.column("Actors", width=300)
        self.tree.column("Role", width=220)
        self.tree.tag_configure("even", background=self.colors["surface"])
        self.tree.tag_configure("odd", background=self.colors["surface_soft"])

        yscroll = AutoHideScrollbar(tree_body, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        right_outer = tk.Frame(content, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        right_outer.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right_outer.grid_columnconfigure(0, weight=1)
        right_outer.grid_rowconfigure(0, weight=1)

        right = ttk.Frame(right_outer, padding=(12, 12, 12, 10), style="Card.TFrame")
        right.grid(row=0, column=0, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        ttk.Button(right, text="Apply Update", style="Primary.TButton", command=self.apply_actor_update).grid(
            row=1, column=0, sticky="ew"
        )
        summary_frame = ttk.Frame(right, padding=(10, 10, 10, 10), style="Surface.TFrame")
        summary_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        summary_frame.columnconfigure(0, weight=1)

        ttk.Label(summary_frame, text="Target Summary", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            summary_frame,
            textvariable=self.context_var,
            justify="left",
            wraplength=320,
            style="SurfaceBody.TLabel",
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(summary_frame, text="Before", style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w")
        self.before_card = self.create_summary_card(summary_frame)
        self.before_card["card"].grid(row=3, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(summary_frame, text="After", style="FieldLabel.TLabel").grid(row=4, column=0, sticky="w")
        self.after_card = self.create_summary_card(summary_frame)
        self.after_card["card"].grid(row=5, column=0, sticky="ew")

        help_text = (
            "Scan one folder, pick an actor name, and update every matching entry in that library."
        )
        footer = ttk.Frame(app, padding=(10, 8), style="Shell.TFrame")
        footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(2, weight=1)

        ttk.Label(footer, text=help_text, justify="left", wraplength=860, style="Shell.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.status_badge = tk.Label(
            footer,
            text="Ready",
            bg=self.colors["accent_soft"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 9),
            padx=10,
            pady=4,
        )
        self.status_badge.grid(row=0, column=1, sticky="w", padx=(12, 12))

        self.status_label = tk.Label(
            footer,
            textvariable=self.status_var,
            bg=self.colors["shell_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        )
        self.status_label.grid(row=0, column=2, sticky="e")

        self.actor_name_var.trace_add("write", lambda *_args: self.refresh_for_selection_change())
        self.new_role_var.trace_add("write", lambda *_args: self.update_summary())
        self.new_thumb_var.trace_add("write", lambda *_args: self.update_summary())
        self.set_status(self.status_var.get())

    def set_status(self, message, tone="neutral"):
        tone_styles = {
            "neutral": ("Ready", self.colors["accent_soft"], self.colors["accent"], self.colors["text"]),
            "success": ("Saved", self.colors["success_soft"], self.colors["success"], self.colors["text"]),
            "warning": ("Note", self.colors["warning_soft"], self.colors["warning"], self.colors["text"]),
            "error": ("Error", self.colors["danger_soft"], self.colors["danger"], self.colors["danger"]),
        }
        badge_text, badge_bg, badge_fg, text_fg = tone_styles.get(tone, tone_styles["neutral"])
        self.status_var.set(message)
        if hasattr(self, "status_badge"):
            self.status_badge.configure(text=badge_text, bg=badge_bg, fg=badge_fg)
        if hasattr(self, "status_label"):
            self.status_label.configure(fg=text_fg)

    def choose_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.folder_var.set(path)

    def scan_folder(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Invalid Folder", "Choose a valid folder first.")
            return

        files = find_nfo_files(folder)
        records = []
        failures = 0
        for path in files:
            try:
                records.append(read_nfo_record(path))
            except ET.ParseError:
                failures += 1

        self.records = records
        self.filtered_records = records[:]
        self.refresh_tree()
        self.refresh_actor_name_list()
        self.set_status(
            f"Scanned {len(records)} files"
            + (f" ({failures} skipped)" if failures else ""),
            "warning" if failures else "success",
        )
        self.update_summary()

    def refresh_tree(self):
        current_name = self.actor_name_var.get().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, record in enumerate(self.filtered_records):
            actor_text = summarize_actor_names(record.actors)
            role_text = role_for_actor_name(record.actors, current_name)
            tag = "even" if index % 2 == 0 else "odd"
            self.tree.insert("", "end", iid=str(index), values=(record.title, actor_text, role_text), tags=(tag,))

    def refresh_actor_name_list(self):
        actor_names = collect_actor_names(self.records)
        self.actor_name_combo["values"] = actor_names
        if actor_names and self.actor_name_var.get() not in actor_names:
            self.actor_name_var.set(actor_names[0])
        elif not actor_names:
            self.actor_name_var.set("")

    def find_preview_actor(self):
        target_name = self.actor_name_var.get().strip()
        if not target_name:
            return None, None

        normalized_target = target_name.casefold()
        for record in self.records:
            for actor in record.actors:
                if actor.name.strip().casefold() == normalized_target:
                    return record, actor
        return None, None

    def refresh_for_selection_change(self):
        self.refresh_tree()
        self.update_summary()

    def create_summary_card(self, parent):
        card = tk.Frame(parent, bg=self.colors["border_soft"], bd=0, highlightthickness=0, padx=1, pady=1)
        card.grid_columnconfigure(0, weight=1)

        body = tk.Frame(card, bg=self.colors["surface"], padx=8, pady=8)
        body.grid(row=0, column=0, sticky="ew")
        body.grid_columnconfigure(1, weight=1)

        media = tk.Frame(body, bg=self.colors["surface"])
        media.grid(row=0, column=0, sticky="nsw")
        thumb_label = tk.Label(media, bg=self.colors["surface"], bd=0)
        thumb_label.thumb_size = (82, 110)
        thumb_label.grid(row=0, column=0, sticky="nsew")

        content = tk.Frame(body, bg=self.colors["surface_soft"], padx=10, pady=8)
        content.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        content.grid_columnconfigure(0, weight=1)

        sort_label = tk.Label(
            content,
            text="#?",
            bg=self.colors["accent_soft"],
            fg=self.colors["accent"],
            padx=8,
            pady=3,
            font=("Segoe UI Semibold", 8),
        )
        sort_label.grid(row=0, column=0, sticky="w")

        name_label = tk.Label(
            content,
            text="Unnamed Actor",
            bg=self.colors["surface_soft"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 12),
            anchor="w",
            justify="left",
            wraplength=180,
        )
        name_label.grid(row=1, column=0, sticky="ew", pady=(8, 3))

        role_label = tk.Label(
            content,
            text="No role",
            bg=self.colors["surface_soft"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
            wraplength=180,
        )
        role_label.grid(row=2, column=0, sticky="ew")

        thumb_text_label = tk.Label(
            content,
            text="No thumb",
            bg=self.colors["surface_soft"],
            fg=self.colors["subtle"],
            font=("Segoe UI", 8),
            justify="left",
            anchor="w",
            wraplength=180,
        )
        thumb_text_label.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        return {
            "card": card,
            "thumb": thumb_label,
            "sort": sort_label,
            "name": name_label,
            "role": role_label,
            "thumb_text": thumb_text_label,
        }

    def get_actor_placeholder_image(self, name, size=(92, 124)):
        key = ((name or "").strip().casefold() or "placeholder", size)
        cached = self.actor_placeholder_cache.get(key)
        if cached is not None:
            return cached

        initials = "".join(part[0] for part in (name or "Actor").split()[:2]).upper() or "A"
        width, height = size
        image = Image.new("RGB", (width, height), self.colors["accent_soft"])
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=max(10, min(width, height) // 7),
            fill=self.colors["accent_soft"],
            outline=self.colors["border"],
        )
        bbox = draw.textbbox((0, 0), initials)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text(
            ((width - text_width) / 2, (height - text_height) / 2 - 2),
            initials,
            fill=self.colors["muted"],
        )
        photo = ImageTk.PhotoImage(image)
        self.actor_placeholder_cache[key] = photo
        return photo

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

    def set_actor_thumb_image(self, label, url, name):
        thumb_size = getattr(label, "thumb_size", (92, 124))
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
            image_bytes = self.fetch_actor_thumb(url)
            self.root.after(0, lambda: self.finish_actor_thumb_image(url, image_bytes))

        Thread(target=worker, daemon=True).start()

    def finish_actor_thumb_image(self, url, image_bytes):
        listeners = self.actor_thumb_requests.pop(url, [])
        photo = None
        if image_bytes is not None:
            thumb_size = listeners[0][2] if listeners else (92, 124)
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

    def set_summary_card_values(self, card_view, actor_name, role, thumb_url, sortorder):
        display_name = actor_name or "Unnamed Actor"
        display_role = role or "No role"
        display_thumb = thumb_url or "No thumb"
        display_sort = (sortorder or "?").strip() or "?"

        card_view["sort"].configure(text=f"#{display_sort}")
        card_view["name"].configure(text=display_name)
        card_view["role"].configure(text=display_role)
        card_view["thumb_text"].configure(text=display_thumb)

        placeholder = self.get_actor_placeholder_image(display_name, size=card_view["thumb"].thumb_size)
        card_view["thumb"].configure(image=placeholder)
        card_view["thumb"].image = placeholder
        if thumb_url and is_allowed_remote_image_url(thumb_url):
            self.set_actor_thumb_image(card_view["thumb"], thumb_url, display_name)

    def clear_summary_card(self, card_view):
        placeholder = self.get_actor_placeholder_image("Actor", size=card_view["thumb"].thumb_size)
        card_view["thumb"].configure(image=placeholder)
        card_view["thumb"].image = placeholder
        card_view["sort"].configure(text="#?")
        card_view["name"].configure(text="No actor selected")
        card_view["role"].configure(text="Choose an actor name from the scanned files.")
        card_view["thumb_text"].configure(text="No thumb")

    def update_summary(self):
        record, actor = self.find_preview_actor()
        if actor is None:
            self.context_var.set("No matching actor found for the current selection.")
            self.clear_summary_card(self.before_card)
            self.clear_summary_card(self.after_card)
            return

        target_name = self.actor_name_var.get().strip()
        after_role = self.new_role_var.get().strip() or actor.role or "(empty)"
        after_thumb = self.new_thumb_var.get().strip() or actor.thumb
        target_count = 0
        normalized_target = target_name.casefold()
        for target in self.records:
            for target_actor in target.actors:
                if target_actor.name.strip().casefold() == normalized_target:
                    target_count += 1
                    break

        self.context_var.set(f"{target_count} matching file{'s' if target_count != 1 else ''} in this scan")
        self.set_summary_card_values(self.before_card, actor.name, actor.role, actor.thumb, actor.sortorder)
        self.set_summary_card_values(self.after_card, actor.name, after_role, after_thumb, actor.sortorder)

    def apply_actor_update(self):
        new_role = self.new_role_var.get().strip()
        new_thumb = self.new_thumb_var.get().strip()
        target_name = self.actor_name_var.get().strip()

        if not target_name:
            messagebox.showerror("Missing Data", "Choose an Actor Name to update.")
            return
        if not any([new_role, new_thumb]):
            messagebox.showerror("Missing Data", "Enter at least one new value to apply.")
            return

        if not self.records:
            messagebox.showerror("No Files Found", "Scan a folder with NFO/XML files first.")
            return

        files_changed = 0
        actor_updates = 0
        failures = []
        for record in self.records:
            try:
                tree = parse_xml_file(record.path)
                replacements = update_actor_fields_by_name_in_tree(
                    tree,
                    target_name=target_name,
                    new_role=new_role,
                    new_thumb=new_thumb,
                )
                if replacements:
                    write_xml_file(tree.getroot(), record.path)
                    files_changed += 1
                    actor_updates += replacements
            except (ET.ParseError, OSError) as exc:
                failures.append(f"{record.path}: {exc}")

        self.scan_folder()
        result_message = f"Updated {actor_updates} actor entries across {files_changed} files."
        if failures:
            failure_count = len(failures)
            preview = "\n".join(failures[:5])
            if failure_count > 5:
                preview += f"\n... and {failure_count - 5} more."
            result_message += f"\n\nFailed to update {failure_count} file(s):\n{preview}"
            self.set_status(f"Updated {actor_updates} actor entries across {files_changed} files. {failure_count} failed.", "warning")
            messagebox.showwarning("Batch Update Completed With Errors", result_message)
            return

        self.set_status(result_message, "success")
        messagebox.showinfo("Batch Update Complete", result_message)


def run():
    root = tk.Tk()
    BatchActorEditor(root)
    root.mainloop()
