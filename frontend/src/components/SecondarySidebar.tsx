/**
 * SecondarySidebar — a contextual second sidebar that sits flush against the
 * main navigation sidebar.
 *
 * The Layout owns a host slot between the nav sidebar and the main content;
 * pages deeper in the tree (e.g. the review step's source-grounding panel)
 * project into that slot with a portal via <SecondarySidebar>. Rendering stays
 * in the owning page's React tree, so state like the active source field flows
 * normally — only the DOM position moves.
 *
 * The sidebar collapses to a slim rail holding just an expand button. Collapse
 * state is local (it resets each time the panel mounts) by design: a fresh
 * review should always open with its evidence visible.
 */
import React, {
  createContext,
  useContext,
  useEffect,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';

interface SlotContextValue {
  host: HTMLElement | null;
  /** Layout tracks how many panels are projected so it can hide an empty slot. */
  setOccupants: React.Dispatch<React.SetStateAction<number>>;
}

const SlotContext = createContext<SlotContextValue | null>(null);

/** Provided by Layout; exposes the slot element to descendant pages. */
export const SecondarySidebarProvider = SlotContext.Provider;

interface SecondarySidebarProps {
  /** Shown in the sidebar header and as the collapsed rail's tooltip. */
  title: string;
  /** Small icon rendered next to the title. */
  icon?: React.ReactNode;
  /** Controlled collapse state; omit to let the sidebar manage its own. */
  collapsed?: boolean;
  /** Notified on expand/collapse so the owning page can react (e.g. hide
      per-field source links while the panel is away). */
  onCollapsedChange?: (collapsed: boolean) => void;
  children: React.ReactNode;
}

export const SecondarySidebar: React.FC<SecondarySidebarProps> = ({
  title,
  icon,
  collapsed: collapsedProp,
  onCollapsedChange,
  children,
}) => {
  const slot = useContext(SlotContext);
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const collapsed = collapsedProp ?? internalCollapsed;
  const setCollapsed = (next: boolean) => {
    setInternalCollapsed(next);
    onCollapsedChange?.(next);
  };

  // Mark the slot occupied for our lifetime so Layout shows it.
  const setOccupants = slot?.setOccupants;
  useEffect(() => {
    if (!setOccupants) return;
    setOccupants((n) => n + 1);
    return () => setOccupants((n) => n - 1);
  }, [setOccupants]);

  if (!slot?.host) return null;

  return createPortal(
    collapsed ? (
      <div className="secondary-sidebar__rail">
        <button
          type="button"
          className="secondary-sidebar__btn"
          onClick={() => setCollapsed(false)}
          aria-label={`Expand ${title}`}
          aria-expanded={false}
          title={title}
        >
          <PanelLeftOpen size={18} />
        </button>
      </div>
    ) : (
      <div className="secondary-sidebar__panel">
        <div className="secondary-sidebar__header">
          <span className="secondary-sidebar__title">
            {icon}
            {title}
          </span>
          <button
            type="button"
            className="secondary-sidebar__btn"
            onClick={() => setCollapsed(true)}
            aria-label={`Collapse ${title}`}
            aria-expanded={true}
          >
            <PanelLeftClose size={16} />
          </button>
        </div>
        <div className="secondary-sidebar__body">{children}</div>
      </div>
    ),
    slot.host,
  );
};
