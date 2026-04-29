import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from app.batch_actor_editor import (
    ActorInfo,
    AutoHideScrollbar,
    NFORecord,
    collect_actor_names,
    find_nfo_files,
    role_for_actor_name,
    summarize_actor_names,
    update_actor_fields_by_name_in_tree,
)
from app.movie_nfo_editor import parse_xml_file, write_xml_file


class BatchActorEditorTests(unittest.TestCase):
    def test_find_nfo_files_scans_nested_folders_recursively(self):
        temp_path = Path("D:/Codex/tests/tmp/multi-root-scan")
        root_one = temp_path / "root-one"
        nested = root_one / "nested"
        root_one.mkdir(parents=True, exist_ok=True)
        nested.mkdir(parents=True, exist_ok=True)

        first_nfo = root_one / "movie-a.nfo"
        second_xml = nested / "movie-b.xml"
        ignored_txt = root_one / "notes.txt"
        try:
            first_nfo.write_text("<movie />", encoding="utf-8")
            second_xml.write_text("<movie />", encoding="utf-8")
            ignored_txt.write_text("ignore", encoding="utf-8")

            self.assertEqual(
                find_nfo_files(str(root_one)),
                sorted([str(first_nfo), str(second_xml)]),
            )
        finally:
            for path in (first_nfo, second_xml, ignored_txt):
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
            for directory in (nested, root_one, temp_path):
                if directory.exists():
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    def test_collect_actor_names_returns_sorted_unique_values(self):
        records = [
            NFORecord(
                path="a.nfo",
                title="A",
                actors=[
                    ActorInfo(name="Beta", role="", thumb="", sortorder="2"),
                    ActorInfo(name="alpha", role="", thumb="", sortorder="10"),
                ],
            ),
            NFORecord(
                path="b.nfo",
                title="B",
                actors=[
                    ActorInfo(name="Beta", role="", thumb="", sortorder="2"),
                    ActorInfo(name="", role="", thumb="", sortorder="1"),
                ],
            ),
        ]
        self.assertEqual(collect_actor_names(records), ["alpha", "Beta"])

    def test_role_for_actor_name_returns_matching_role_case_insensitively(self):
        role = role_for_actor_name(
            [
                ActorInfo(name="Actor One", role="Lead", thumb="", sortorder=""),
                ActorInfo(name="Actor Two", role="Support", thumb="", sortorder=""),
            ],
            "actor two",
        )
        self.assertEqual(role, "Support")

    def test_update_actor_fields_by_name_updates_all_matching_actor_names(self):
        root = ET.fromstring(
            """
            <movie>
              <actor><name>Alpha</name><role>Old A</role></actor>
              <actor><name>Beta</name><role>Old B</role></actor>
              <actor><name>alpha</name><role>Old A2</role></actor>
            </movie>
            """
        )
        tree = ET.ElementTree(root)
        replacements = update_actor_fields_by_name_in_tree(
            tree,
            target_name="ALPHA",
            new_role="Updated",
            new_thumb="alpha.webp",
        )
        self.assertEqual(replacements, 2)
        actors = root.findall("actor")
        self.assertEqual(actors[0].findtext("role"), "Updated")
        self.assertEqual(actors[0].findtext("thumb"), "alpha.webp")
        self.assertEqual(actors[1].findtext("role"), "Old B")
        self.assertEqual(actors[2].findtext("role"), "Updated")

    def test_update_actor_fields_by_name_returns_zero_when_name_is_empty(self):
        root = ET.fromstring("<movie><actor><name>Alpha</name></actor></movie>")
        tree = ET.ElementTree(root)
        self.assertEqual(
            update_actor_fields_by_name_in_tree(tree, target_name="", new_role="Updated", new_thumb="thumb.webp"),
            0,
        )

    def test_summarize_actor_names_lists_names_only(self):
        summary = summarize_actor_names(
            [
                ActorInfo(name="Actor One", role="Lead", thumb="", sortorder="0"),
                ActorInfo(name="Actor Two", role="", thumb="", sortorder="1"),
            ]
        )
        self.assertEqual(summary, "Actor One, Actor Two")

    def test_auto_hide_scrollbar_reappears_when_content_needs_scrolling(self):
        root = tk.Tk()
        root.withdraw()
        try:
            frame = ttk.Frame(root)
            frame.grid()

            scrollbar = AutoHideScrollbar(frame, orient="vertical")
            scrollbar.grid(row=0, column=0)

            scrollbar.set("0.0", "1.0")
            root.update_idletasks()
            self.assertEqual(scrollbar.winfo_manager(), "")

            scrollbar.set("0.0", "0.5")
            root.update_idletasks()
            self.assertEqual(scrollbar.winfo_manager(), "grid")
        finally:
            root.destroy()

    def test_round_trip_save_updates_exact_actor_name_in_multi_actor_file(self):
        xml = """<movie>
  <actor>
    <name>Hana Himesaki</name>
    <role>Hana Himesaki</role>
    <type>Actor</type>
    <sortorder>0</sortorder>
    <thumb>https://www.javdatabase.com/idolimages/full/hana-himesaki.webp</thumb>
  </actor>
  <actor>
    <name>Natsuki Hoshino</name>
    <role>Natsuki Hoshino</role>
    <type>Actor</type>
    <sortorder>1</sortorder>
    <thumb>https://www.javdatabase.com/idolimages/full/natsuki-hoshino.webp</thumb>
  </actor>
  <actor>
    <name>Ai Abe</name>
    <role>Ai Abe, Airi Sato, あべ藍</role>
    <type>Actor</type>
    <sortorder>2</sortorder>
    <thumb>https://www.javdatabase.com/idolimages/full/ai-abe.webp</thumb>
  </actor>
</movie>"""
        temp_dir = Path("D:/Codex/tests/tmp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        path = temp_dir / "movie-roundtrip.nfo"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(xml)

            tree = parse_xml_file(path)
            replacements = update_actor_fields_by_name_in_tree(
                tree,
                target_name="Natsuki Hoshino",
                new_role="Updated Role",
                new_thumb="https://example.com/new.webp",
            )
            self.assertEqual(replacements, 1)
            write_xml_file(tree.getroot(), path)

            reloaded = parse_xml_file(path).getroot().findall("actor")
            self.assertEqual(reloaded[0].findtext("role"), "Hana Himesaki")
            self.assertEqual(reloaded[1].findtext("role"), "Updated Role")
            self.assertEqual(reloaded[1].findtext("thumb"), "https://example.com/new.webp")
            self.assertEqual(reloaded[2].findtext("role"), "Ai Abe, Airi Sato, あべ藍")
        finally:
            if path.exists():
                try:
                    path.unlink()
                except PermissionError:
                    pass


if __name__ == "__main__":
    unittest.main()
