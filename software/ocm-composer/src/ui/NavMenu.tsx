// SPDX-License-Identifier: AGPL-3.0-or-later
// A hamburger button + dropdown for switching between the app's top-level
// pages. Pure UI state (open/closed) owned here; WHICH page is active and
// what the pages even are stays with the caller (App.tsx) -- this
// component doesn't know or care what a "page" means beyond an id/label.

import { useEffect, useRef, useState } from "react";

export interface NavPage {
  id: string;
  label: string;
}

export interface NavMenuProps {
  pages: NavPage[];
  activePage: string;
  onSelect: (id: string) => void;
}

export function NavMenu({ pages, activePage, onSelect }: NavMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className="nav-menu" ref={containerRef}>
      <button type="button" className="nav-menu__button" aria-label="Menu" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="nav-menu__bar" />
        <span className="nav-menu__bar" />
        <span className="nav-menu__bar" />
      </button>
      {open && (
        <ul className="nav-menu__dropdown" role="menu">
          {pages.map((page) => (
            <li key={page.id} role="none">
              <button
                type="button"
                role="menuitem"
                className={page.id === activePage ? "nav-menu__item nav-menu__item--active" : "nav-menu__item"}
                onClick={() => {
                  onSelect(page.id);
                  setOpen(false);
                }}
              >
                {page.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
