import os
import sys
import tkinter as tk

from app.batch_actor_editor import BatchActorEditor
from app.movie_nfo_editor import MovieNFOEditor, log_exception
from tkinter import messagebox


class CombinedMovieToolsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JAV NFO Creator")
        self.root.geometry("1380x860")
        self.root.minsize(1120, 720)
        self.apply_window_icon()

        self.current_tab = "nfo"
        self.tab_buttons = {}

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = tk.Frame(self.root, bg="#e6edf5")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        tab_bar = tk.Frame(shell, bg="#ffffff", padx=12, pady=6)
        tab_bar.grid(row=0, column=0, sticky="ew")

        tab_strip = tk.Frame(tab_bar, bg="#e9eff6", padx=4, pady=3)
        tab_strip.pack(anchor="w")

        content = tk.Frame(shell, bg="#eef3f8")
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.nfo_host = tk.Frame(content, bg="#eef3f8")
        self.batch_host = tk.Frame(content, bg="#eef3f8")
        self.nfo_host.grid(row=0, column=0, sticky="nsew")
        self.batch_host.grid(row=0, column=0, sticky="nsew")
        self.nfo_host.columnconfigure(0, weight=1)
        self.nfo_host.rowconfigure(0, weight=1)
        self.batch_host.columnconfigure(0, weight=1)
        self.batch_host.rowconfigure(0, weight=1)

        self.batch_editor = BatchActorEditor(self.root, host=self.batch_host, configure_window=False)
        self.nfo_editor = MovieNFOEditor(self.root, host=self.nfo_host, configure_window=False, create_menu=True)

        colors = self.nfo_editor.colors
        self.root.configure(bg=colors["page_bg"])
        shell.configure(bg=colors["border_soft"])
        content.configure(bg=colors["page_bg"])
        self.nfo_host.configure(bg=colors["page_bg"])
        self.batch_host.configure(bg=colors["page_bg"])

        self.tab_buttons["nfo"] = tk.Label(
            tab_strip,
            text="NFO Editor",
            bg=colors["surface"],
            fg=colors["text"],
            padx=16,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.tab_buttons["nfo"].pack(side="left")
        self.tab_buttons["nfo"].bind("<Button-1>", lambda _event: self.show_tab("nfo"))

        self.tab_buttons["batch"] = tk.Label(
            tab_strip,
            text="Batch Editor",
            bg="#e9eff6",
            fg=colors["muted"],
            padx=16,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.tab_buttons["batch"].pack(side="left", padx=(4, 0))
        self.tab_buttons["batch"].bind("<Button-1>", lambda _event: self.show_tab("batch"))

        self.show_tab("nfo")
        self.root.report_callback_exception = self.handle_tk_exception

    def apply_window_icon(self):
        try:
            if getattr(sys, "frozen", False):
                self.root.iconbitmap(default=sys.executable)
            else:
                icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "jav_nfo_creator.ico")
                if os.path.exists(icon_path):
                    self.root.iconbitmap(default=icon_path)
        except Exception:
            pass

    def show_tab(self, tab_name):
        self.current_tab = tab_name
        colors = self.nfo_editor.colors
        if tab_name == "nfo":
            self.nfo_host.tkraise()
        else:
            self.batch_host.tkraise()

        for key, button in self.tab_buttons.items():
            selected = key == tab_name
            button.configure(
                bg=colors["surface"] if selected else "#e9eff6",
                fg=colors["text"] if selected else colors["muted"],
            )

    def handle_tk_exception(self, exc_type, exc_value, exc_traceback):
        log_path = log_exception(exc_type, exc_value, exc_traceback)
        messagebox.showerror(
            "Application Error",
            f"The application hit an unexpected error.\n\nDetails were saved to:\n{log_path}",
        )
        self.root.destroy()


def run():
    root = tk.Tk()
    CombinedMovieToolsApp(root)
    root.mainloop()
