from __future__ import annotations

import re
import time
from typing import List, Optional

from .groups import GROUPS_DIR, group_description, parse_group, skill_description
from .install import install_type, load_installed, save_installed
from .utils import BLUE, BOLD, CYAN, GREEN, NC, RED, YELLOW, clear_screen, info, ok, warn


def show_group_menu() -> Optional[List[str]]:
    selected_groups: List[str] = []
    groups = []
    for file_path in sorted(GROUPS_DIR.glob("*.group")):
        if file_path.stem == "all":
            continue
        if not parse_group(file_path):
            continue
        groups.append((file_path.stem, file_path))
    while True:
        clear_screen()
        print(f"{BOLD}╔══════════════════════════════════════════════╗{NC}")
        print(f"{BOLD}║       AI Management Installer                ║{NC}")
        print(f"{BOLD}║       Select Skill Groups                    ║{NC}")
        print(f"{BOLD}╚══════════════════════════════════════════════╝{NC}")
        print()
        for index, (name, file_path) in enumerate(groups, start=1):
            desc = group_description(file_path)
            count = len(parse_group(file_path))
            marker = f"{GREEN}✓ {NC}" if name in selected_groups else "  "
            print(f"  {marker}{BLUE}{index:2d}){NC} {name:<25} {YELLOW}({count} skills){NC}  {desc}")
        print()
        print(f"  {GREEN}✓ {BLUE} a){NC} Select ALL groups")
        print(f"  {RED}✗ {BLUE} n){NC} Deselect all")
        print()
        print(f"  {BOLD}Selected: {len(selected_groups)} groups{NC}")
        print()
        choice = input(f"  Enter number to toggle, {GREEN}a{NC}ll, {RED}n{NC}one, {CYAN}i{NC}nstall, or {RED}q{NC}uit:\n  > ").strip()
        if choice.lower() == "q":
            return None
        if choice.lower() == "a":
            selected_groups = [name for name, _ in groups]
            continue
        if choice.lower() == "n":
            selected_groups = []
            continue
        if choice.lower() == "i":
            if not selected_groups:
                warn("No groups selected")
                time.sleep(1)
                continue
            resolved: List[str] = []
            for group_name in selected_groups:
                for name, file_path in groups:
                    if name == group_name:
                        resolved.extend(parse_group(file_path))
            return sorted(set(resolved))
        if choice.isdigit() and 1 <= int(choice) <= len(groups):
            group_name = groups[int(choice) - 1][0]
            if group_name in selected_groups:
                selected_groups.remove(group_name)
            else:
                selected_groups.append(group_name)


def show_individual_menu(all_skills: List[str]) -> Optional[List[str]]:
    selected_skills: List[str] = []
    installed = load_installed()
    page = 0
    page_size = 20
    total = len(all_skills)
    total_pages = max(1, (total + page_size - 1) // page_size)
    while True:
        clear_screen()
        print(f"{BOLD}╔══════════════════════════════════════════════╗{NC}")
        print(f"{BOLD}║       AI Management Installer                ║{NC}")
        print(f"{BOLD}║       Select Individual Skills               ║{NC}")
        print(f"{BOLD}╚══════════════════════════════════════════════╝{NC}")
        print(f"  Page {page + 1}/{total_pages}  |  Selected: {len(selected_skills)}/{total}")
        print()
        start = page * page_size
        end = min(start + page_size, total)
        for absolute_index, idx in enumerate(range(start, end), start=start + 1):
            name = all_skills[idx]
            marker = f"{GREEN}✓ {NC}" if name in selected_skills else "  "
            installed_marker = f" {CYAN}[installed]{NC}" if name in installed else ""
            desc = skill_description(name)
            if len(desc) > 55:
                desc = desc[:52] + "..."
            print(f"  {marker}{BLUE}{absolute_index:2d}){NC} {name:<35} {desc}{installed_marker}")
        print()
        print(f"  {CYAN}<{NC} prev | {CYAN}>{NC} next | {GREEN}a{NC}ll | {RED}n{NC}one | {CYAN}i{NC}nstall | {RED}q{NC}uit")
        choice = input("  > ").strip()
        if choice.lower() == "q":
            return None
        if choice in {"<", "p", "P"}:
            page = max(0, page - 1)
            continue
        if choice in {">", "next", "n_page", "N_page"}:
            page = min(total_pages - 1, page + 1)
            continue
        if choice.lower() == "a":
            selected_skills = list(all_skills)
            continue
        if choice.lower() == "n":
            selected_skills = []
            continue
        if choice.lower() == "i":
            if not selected_skills:
                warn("No skills selected")
                time.sleep(1)
                continue
            return selected_skills
        if re.fullmatch(r"\d+-\d+", choice):
            start_num, end_num = [int(part) for part in choice.split("-", 1)]
            for number in range(start_num, min(end_num, total) + 1):
                skill_name = all_skills[number - 1]
                if skill_name not in selected_skills:
                    selected_skills.append(skill_name)
            continue
        if choice.isdigit() and 1 <= int(choice) <= total:
            skill_name = all_skills[int(choice) - 1]
            if skill_name in selected_skills:
                selected_skills.remove(skill_name)
            else:
                selected_skills.append(skill_name)


def uninstall_menu() -> None:
    installed = load_installed()
    if not installed:
        warn("No skills installed")
        return
    print()
    print(f"{BOLD}── Installed Skills ──{NC}")
    for index, skill in enumerate(installed, start=1):
        print(f"  {BLUE}{index:2d}){NC} {skill}")
    print()
    choice = input(f"  Enter numbers to uninstall (comma-separated), {RED}a{NC}ll, or {RED}q{NC}uit:\n  > ").strip()
    if choice.lower() == "q":
        return
    if choice.lower() == "a":
        save_installed([])
        ok("Uninstalled all skills")
        return
    updated = list(installed)
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(installed):
            skill = installed[int(part) - 1]
            updated = [value for value in updated if value != skill]
            ok(f"Uninstalled: {skill}")
    save_installed(updated)


def main_menu(all_skills: List[str]) -> None:
    while True:
        clear_screen()
        installed = load_installed()
        print(f"{BOLD}╔══════════════════════════════════════════════╗{NC}")
        print(f"{BOLD}║       AI Management Installer                ║{NC}")
        print(f"{BOLD}╚══════════════════════════════════════════════╝{NC}")
        print()
        print(f"  {CYAN}{len(all_skills)}{NC} skills available  |  {GREEN}{len(installed)}{NC} installed")
        print()
        print(f"  {BLUE}1){NC} Browse by {BOLD}group{NC}        (categories of related skills)")
        print(f"  {BLUE}2){NC} Browse {BOLD}individual{NC}      (pick specific skills)")
        print(f"  {BLUE}3){NC} Install {GREEN}all{NC} skills")
        print(f"  {BLUE}4){NC} {RED}Uninstall{NC} skills")
        print(f"  {BLUE}5){NC} Show installed")
        print(f"  {BLUE}q){NC} Quit")
        print()
        choice = input("  > ").strip()
        if choice == "1":
            selected = show_group_menu()
            if selected:
                install_type("skills", selected)
                input("  Press Enter to continue...")
        elif choice == "2":
            selected = show_individual_menu(all_skills)
            if selected:
                install_type("skills", selected)
                input("  Press Enter to continue...")
        elif choice == "3":
            install_type("skills", all_skills)
            input("  Press Enter to continue...")
        elif choice == "4":
            uninstall_menu()
            input("  Press Enter to continue...")
        elif choice == "5":
            print()
            print(f"{BOLD}── Installed Skills ──{NC}")
            if not installed:
                info("No skills installed")
            else:
                for skill in installed:
                    print(f"  {GREEN}✓{NC} {skill}")
            print()
            input("  Press Enter to continue...")
        elif choice.lower() == "q":
            return
