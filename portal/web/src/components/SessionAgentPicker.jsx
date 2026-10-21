// Copyright (c) Microsoft. All rights reserved.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { matchesAgentSearch } from "../../../static/handoff/handoff-core.mjs";
import { Icon } from "./ConfigControls.jsx";

export function SessionAgentPicker({
  id, agents, value, selectedName, disabled, loading, busy, onChange, onResolve,
  onReset, "aria-describedby": describedBy,
}) {
  const [open, setOpen] = useState(false);
  const [activeName, setActiveName] = useState("");
  const [placement, setPlacement] = useState({ above: false, maxHeight: 360 });
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const listId = `${id}-options`;
  const query = value.trim() === selectedName ? "" : value.trim();
  const filtered = agents.filter((item) => matchesAgentSearch(item.name, query));
  const activeIndex = filtered.findIndex((item) => item.name === activeName);
  const expanded = open && !disabled;

  useEffect(() => {
    const closeOutside = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  useEffect(() => {
    setOpen(false);
    setActiveName("");
  }, [selectedName, disabled]);

  useLayoutEffect(() => {
    if (!expanded) return;
    const position = () => {
      const rect = rootRef.current.getBoundingClientRect();
      const viewport = window.visualViewport;
      const top = viewport?.offsetTop || 0;
      const bottom = top + (viewport?.height || window.innerHeight);
      const below = bottom - rect.bottom - 12;
      const above = rect.top - top - 12;
      const opensAbove = below < 240 && above > below;
      const maxHeight = Math.max(0, Math.min(360, opensAbove ? above : below));
      setPlacement((current) => current.above === opensAbove && current.maxHeight === maxHeight
        ? current : { above: opensAbove, maxHeight });
    };
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    window.visualViewport?.addEventListener("resize", position);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
      window.visualViewport?.removeEventListener("resize", position);
    };
  }, [expanded]);

  useEffect(() => {
    if (expanded && activeName) {
      listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
    }
  }, [expanded, activeName]);

  const choose = (name) => {
    if (busy) return;
    inputRef.current?.focus();
    setOpen(false);
    setActiveName("");
    void onResolve(name);
  };

  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      setActiveName("");
      onReset();
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(expanded && activeIndex >= 0 ? filtered[activeIndex].name : value);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      if (!filtered.length) return;
      const index = event.key === "ArrowDown"
        ? Math.min(filtered.length - 1, activeIndex + 1)
        : activeIndex < 0 ? filtered.length - 1 : Math.max(0, activeIndex - 1);
      setActiveName(filtered[index].name);
    } else if (expanded && activeIndex >= 0 && (event.key === "Home" || event.key === "End")) {
      event.preventDefault();
      setActiveName(filtered[event.key === "Home" ? 0 : filtered.length - 1].name);
    }
  };

  return (
    <div className={`session-agent-picker${expanded ? " is-open" : ""}`} ref={rootRef}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}>
      <Icon name="agent" className="session-agent-input-icon" />
      <input ref={inputRef} id={id} type="search" role="combobox"
        value={value} autoComplete="off" spellCheck="false" disabled={disabled}
        placeholder={loading ? "Loading voice agents..." : "Search or choose an Agent"}
        title={value || "Choose a Voice Agent"}
        aria-autocomplete="list" aria-expanded={expanded} aria-busy={loading || busy}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={expanded && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        aria-describedby={[describedBy, expanded ? `${listId}-help` : ""].filter(Boolean).join(" ") || undefined}
        onFocus={() => setOpen(true)} onClick={() => setOpen(true)}
        onChange={(event) => {
          setActiveName("");
          setOpen(true);
          onChange(event.target.value);
        }}
        onKeyDown={onKeyDown} />
      <button className="session-agent-toggle" type="button" tabIndex={-1}
        aria-label="Show Agent suggestions" aria-expanded={expanded}
        disabled={disabled || busy}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          inputRef.current?.focus();
          setOpen(!expanded);
          setActiveName("");
        }}>
        <Icon name="chevron" />
      </button>
      {expanded ? (
        <div className={`session-agent-menu${placement.above ? " opens-above" : ""}`}
          style={{ maxHeight: placement.maxHeight }}>
          <div className="session-agent-menu-heading">
            <strong>Voice Agents</strong><span>{filtered.length} / {agents.length}</span>
          </div>
          <div id={listId} ref={listRef} className="session-agent-options"
            role="listbox" aria-label="Session agents">
            {filtered.map((item, index) => (
              <button key={item.name} id={`${listId}-${index}`}
                className="session-agent-option" type="button" role="option" tabIndex={-1}
                aria-label={item.name} aria-selected={item.name === selectedName}
                aria-describedby={`${listId}-${index}-meta`}
                data-active={item.name === activeName} title={item.name} disabled={busy}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveName(item.name)}
                onClick={() => choose(item.name)}>
                <span className="session-agent-avatar"><Icon name="agent" /></span>
                <span className="session-agent-option-copy">
                  <strong>{item.name}</strong>
                  <span className="session-agent-option-meta" id={`${listId}-${index}-meta`}>
                    <span>{item.model || item.targetAgent?.name || "Voice Agent"}</span>
                    <span className="session-agent-version">v{item.version || "latest"}</span>
                  </span>
                </span>
                {item.name === selectedName
                  ? <span className="session-agent-selected">Selected</span>
                  : <Icon name="chevron" className="session-agent-option-arrow" />}
              </button>
            ))}
            {!filtered.length ? (
              <div className="session-agent-empty" role="status">
                {query
                  ? "No loaded Agents match. Press Enter to look up the exact name."
                  : "No Voice Agents loaded yet."}
              </div>
            ) : null}
          </div>
          <div className="session-agent-menu-help" id={`${listId}-help`}>
            Arrow keys to browse. Enter to select.
          </div>
        </div>
      ) : null}
    </div>
  );
}
