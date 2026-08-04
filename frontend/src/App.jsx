import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Chip,
  CircularProgress,
  Dialog,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Typography
} from "@mui/material";
import MovieFilterIcon from "@mui/icons-material/MovieFilter";
import FiberManualRecordIcon from "@mui/icons-material/FiberManualRecord";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloseIcon from "@mui/icons-material/Close";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";

const easeOutQuint = (value) => 1 - Math.pow(1 - value, 5);

function FilmFrame({ frame, selected, register }) {
  return (
    <article
      ref={(node) => register(frame.id, node)}
      className={"film-frame" + (selected ? " is-selected" : "")}
      data-frame-id={frame.id}
    >
      <div className="frame-number">{String(frame.sceneIndex).padStart(3, "0")}</div>
      <img src={frame.displayUrl} alt={frame.label} loading="lazy" />
      <div className="frame-caption">
        <span>{frame.frameType.toUpperCase()}</span>
        <span>
          {frame.frameType === "chapter"
            ? frame.movieStartTimecode
            : frame.bestSimilarity == null
            ? "ORIGINAL"
            : frame.bestSimilarity.toFixed(2) + "%"}
        </span>
      </div>
    </article>
  );
}

function Theater({ frame }) {
  return (
    <Paper className="theater" elevation={12}>
      <div className="theater-proscenium">
        <div className="curtain curtain-left" />
        <div className="curtain curtain-right" />
        <div className="screen-shell">
          {frame?.clipUrl ? (
            <video key={frame.clipUrl} controls preload="metadata" src={frame.clipUrl} />
          ) : (
            <div className="video-empty">Clip unavailable</div>
          )}
        </div>
        <div className="audience">
          <i /><i /><i /><i /><i /><i />
        </div>
      </div>
    </Paper>
  );
}

function GalleryTile({ title, url, similarity, original, best, onExpand }) {
  return (
    <Paper
      className={
        "gallery-tile" +
        (best ? " best" : "") +
        (onExpand && url ? " expandable" : "")
      }
      elevation={0}
      onClick={onExpand && url ? onExpand : undefined}
      role={onExpand && url ? "button" : undefined}
      tabIndex={onExpand && url ? 0 : undefined}
      onKeyDown={(event) => {
        if (onExpand && url && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onExpand();
        }
      }}
    >
      <div className="tile-image">
        {url ? <img src={url} alt={title} loading="lazy" /> : <div className="pending-tile">DEVELOPING</div>}
        {best && <span className="best-badge"><AutoAwesomeIcon fontSize="inherit" /> BEST</span>}
      </div>
      <div className="tile-meta">
        <Typography variant="caption">{title}</Typography>
        <Typography variant="caption" color={original ? "text.secondary" : "primary.main"}>
          {original ? "SOURCE" : similarity == null ? "PENDING" : similarity.toFixed(2) + "%"}
        </Typography>
      </div>
    </Paper>
  );
}

function CharacterDetails({ details }) {
  if (!details) return <Typography color="text.secondary">No details available.</Typography>;
  return (
    <div className="detail-sections">
      {Object.entries(details).map(([section, value]) => (
        <section key={section}>
          <Typography variant="overline">{section.replaceAll("_", " ")}</Typography>
          {value && typeof value === "object" ? (
            <dl>
              {Object.entries(value).map(([key, content]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{String(content)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <Typography variant="body2">{String(value ?? "")}</Typography>
          )}
        </section>
      ))}
    </div>
  );
}

function BookCastCard({ member, onExpandImage }) {
  const primaryImg = member.primaryImageUrl;
  const initials = member.canonicalName
    .split(/\s+/)
    .map((word) => word[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase() || "?";

  const details = [
    { label: "Face", value: member.face },
    { label: "Skin Tone", value: member.skinTone },
    { label: "Eyes", value: member.eyes },
    { label: "Hair", value: member.hair },
    { label: "Build", value: member.build },
    { label: "Posture", value: member.posture },
    { label: "Emotion", value: member.emotion },
    { label: "Action", value: member.action },
    { label: "Fighting Move", value: member.fightingMove },
    { label: "Clothing / Wardrobe", value: member.clothing || member.wardrobe },
    { label: "Accessories", value: member.accessories },
    { label: "Color Info", value: member.colorInformation }
  ].filter((item) => Boolean(item.value));

  return (
    <article className="bookcast-card" id={member.id}>
      <div className="bookcast-left">
        <div className="bookcast-image-container">
          {primaryImg ? (
            <img
              src={primaryImg}
              alt={member.canonicalName}
              loading="lazy"
              onClick={() =>
                onExpandImage({
                  url: primaryImg,
                  title: member.canonicalName,
                  caption: member.firstAppearanceSubtitle
                })
              }
            />
          ) : (
            <div className="bookcast-placeholder">
              <div className="bookcast-placeholder-initials">{initials}</div>
              <div className="bookcast-placeholder-label">Image Pending</div>
            </div>
          )}
        </div>
        <div className="bookcast-image-meta">
          <span>{primaryImg ? "RENDERED PORTRAIT" : "NO IMAGE YET"}</span>
          {member.imageGenerations?.[0]?.genaimodel && (
            <span className="bookcast-model-tag">{member.imageGenerations[0].genaimodel}</span>
          )}
        </div>
      </div>

      <div className="bookcast-right">
        <div className="bookcast-header">
          <h2 className="bookcast-title">{member.canonicalName}</h2>
          <div className="bookcast-subtitle">First Appearance: {member.firstAppearanceSubtitle}</div>
        </div>

        <div className="bookcast-tags">
          {member.entityType && (
            <span className="bookcast-badge entity-type">{member.entityType}</span>
          )}
          {member.speciesOrObjectType && (
            <span className="bookcast-badge">{member.speciesOrObjectType}</span>
          )}
          {member.confidence && (
            <span className="bookcast-badge confidence">Confidence: {member.confidence}</span>
          )}
        </div>

        {member.firstMentionSentence && (
          <div className="bookcast-section bookcast-firstmention">
            <span className="bookcast-section-title">First Mention in the Text</span>
            <blockquote className="bookcast-quote">{member.firstMentionSentence}</blockquote>
            {member.firstMentionCitation && (
              <cite className="bookcast-cite">{member.firstMentionCitation}</cite>
            )}
          </div>
        )}

        {member.descriptivePhrases?.length > 0 && (
          <div className="bookcast-section">
            <span className="bookcast-section-title">Descriptive Phrases Nearby</span>
            <ul className="bookcast-phrase-list">
              {member.descriptivePhrases.map((p, i) => (
                <li key={i}>
                  <span className="bookcast-phrase-text">{p.text}</span>
                  {p.page != null && <span className="bookcast-phrase-page">p. {p.page}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {member.portraitDescription && (
          <div className="bookcast-section">
            <span className="bookcast-section-title">Portrait Description</span>
            <div className="bookcast-section-body">{member.portraitDescription}</div>
          </div>
        )}

        {member.zimageturboPrompt && (
          <div className="bookcast-section">
            <span className="bookcast-section-title">Optimized Z-Image Turbo Prompt</span>
            <div className="bookcast-prompt-box">{member.zimageturboPrompt}</div>
          </div>
        )}

        {details.length > 0 && (
          <div className="bookcast-section">
            <span className="bookcast-section-title">Character Attributes</span>
            <div className="bookcast-details-grid">
              {details.map((d, i) => (
                <div key={i} className="bookcast-detail-item">
                  <span className="bookcast-detail-label">{d.label}</span>
                  <span className="bookcast-detail-value">{String(d.value)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {member.evidenceNotes && (
          <div className="bookcast-section">
            <span className="bookcast-section-title">Evidence & Provenance</span>
            <div className="bookcast-evidence-box">{member.evidenceNotes}</div>
          </div>
        )}
      </div>
    </article>
  );
}

function BookCastView({ bookCast, onExpandImage }) {
  const [search, setSearch] = useState("");
  const [bookFilter, setBookFilter] = useState("all");
  const [imageFilter, setImageFilter] = useState("all");
  const [sortMode, setSortMode] = useState("chronological");

  const filtered = useMemo(() => {
    const list = bookCast.filter((member) => {
      if (search) {
        const q = search.toLowerCase();
        const nameMatch = member.canonicalName?.toLowerCase().includes(q);
        const keyMatch = member.identityKey?.toLowerCase().includes(q);
        const descMatch = member.portraitDescription?.toLowerCase().includes(q);
        if (!nameMatch && !keyMatch && !descMatch) return false;
      }
      if (bookFilter !== "all") {
        if (member.firstAppearanceBook?.toLowerCase() !== bookFilter.toLowerCase()) return false;
      }
      if (imageFilter === "has_image" && !member.primaryImageUrl) return false;
      if (imageFilter === "pending" && member.primaryImageUrl) return false;
      return true;
    });

    return list.sort((a, b) => {
      if (sortMode === "name") {
        return a.canonicalName.localeCompare(b.canonicalName);
      }
      // Default: Chronological (Book -> Chapter -> Page -> Passage -> Name)
      if ((a.bookOrder ?? 99) !== (b.bookOrder ?? 99)) return (a.bookOrder ?? 99) - (b.bookOrder ?? 99);
      if ((a.chapterNum ?? 999) !== (b.chapterNum ?? 999)) return (a.chapterNum ?? 999) - (b.chapterNum ?? 999);
      if ((a.pageNum ?? 9999) !== (b.pageNum ?? 9999)) return (a.pageNum ?? 9999) - (b.pageNum ?? 9999);
      if ((a.passageNum ?? 9999) !== (b.passageNum ?? 9999)) return (a.passageNum ?? 9999) - (b.passageNum ?? 9999);
      return a.canonicalName.localeCompare(b.canonicalName);
    });
  }, [bookCast, search, bookFilter, imageFilter, sortMode]);

  return (
    <div className="bookcast-workspace">
      <div className="bookcast-toolbar">
        <div className="bookcast-search-group">
          <input
            type="text"
            className="bookcast-search-input"
            placeholder="Search cast by name, keywords, or identity..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="bookcast-filter-group">
          <button
            type="button"
            className={"bookcast-filter-btn" + (bookFilter === "all" ? " active" : "")}
            onClick={() => setBookFilter("all")}
          >
            All Books
          </button>
          <button
            type="button"
            className={"bookcast-filter-btn" + (bookFilter === "unsouled" ? " active" : "")}
            onClick={() => setBookFilter("unsouled")}
          >
            Unsouled
          </button>
          <button
            type="button"
            className={"bookcast-filter-btn" + (bookFilter === "soulsmith" ? " active" : "")}
            onClick={() => setBookFilter("soulsmith")}
          >
            Soulsmith
          </button>
          <button
            type="button"
            className={"bookcast-filter-btn" + (imageFilter === "has_image" ? " active" : "")}
            onClick={() => setImageFilter(imageFilter === "has_image" ? "all" : "has_image")}
          >
            With Image ({bookCast.filter((c) => c.primaryImageUrl).length})
          </button>

          <div style={{ width: 1, height: 20, background: '#3c3225', margin: '0 4px' }} />

          <button
            type="button"
            className={"bookcast-filter-btn" + (sortMode === "chronological" ? " active" : "")}
            onClick={() => setSortMode("chronological")}
            title="Sort by book, chapter & passage chronological appearance"
          >
            Sort: Chronological
          </button>
          <button
            type="button"
            className={"bookcast-filter-btn" + (sortMode === "name" ? " active" : "")}
            onClick={() => setSortMode("name")}
            title="Sort alphabetically by character name"
          >
            Sort: A–Z
          </button>
        </div>
        <div className="bookcast-count-badge">
          Showing {filtered.length} of {bookCast.length} Characters
        </div>
      </div>

      <div className="bookcast-grid">
        {filtered.map((member) => (
          <BookCastCard key={member.id} member={member} onExpandImage={onExpandImage} />
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("clips");
  const [selectedBatch, setSelectedBatch] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedCastId, setSelectedCastId] = useState(null);
  const [castGenerationIndexes, setCastGenerationIndexes] = useState({});
  const [clipDescriptionOpen, setClipDescriptionOpen] = useState(false);
  const [error, setError] = useState("");
  const [expandedImage, setExpandedImage] = useState(null);
  const railRef = useRef(null);
  const nodesRef = useRef(new Map());
  const snapTimerRef = useRef(null);
  const animationRef = useRef(null);
  const lastInputRef = useRef(0);
  const dragRef = useRef({ active: false, y: 0, time: 0, moved: false });
  const velocityRef = useRef(0);
  const momentumRef = useRef(false);
  const clickRef = useRef({ frameId: null, time: 0 });

  const loadState = useCallback(async () => {
    try {
      const response = await fetch(import.meta.env.PROD ? "/state.json" : "/api/state", {
        cache: "no-store"
      });
      if (!response.ok) throw new Error("Monitor API returned " + response.status);
      const next = await response.json();
      setData(next);
      setSelectedBatch((current) => current || next.selectedBatch || next.batches?.[0]?.batchName || null);
      setSelectedId((current) => current || next.frames[0]?.id || null);
      setError("");
    } catch (reason) {
      setError(reason.message);
    }
  }, []);

  const batches = data?.batches || [];
  const activeBatch = batches.some((batch) => batch.batchName === selectedBatch)
    ? selectedBatch
    : data?.selectedBatch || batches[0]?.batchName;
  const batchFrames = data?.framesByBatch?.[activeBatch] || data?.frames || [];
  const stats = mode === "clips"
    ? data?.statsByBatch?.[activeBatch] || data?.stats || {}
    : data?.stats || {};

  useEffect(() => {
    loadState();
    if (import.meta.env.PROD) return undefined;
    const events = new EventSource("/api/events");
    events.addEventListener("update", loadState);
    events.onerror = () => setError("Live connection interrupted; retrying...");
    return () => events.close();
  }, [loadState]);

  const selectedIndex = useMemo(
    () => {
      const items = mode === "clips" ? batchFrames : data?.chapters;
      return items?.findIndex((item) => item.id === selectedId) ?? -1;
    },
    [batchFrames, data, mode, selectedId]
  );
  const reelItems = mode === "clips" ? batchFrames : data?.chapters || [];
  const selected = selectedIndex >= 0 ? reelItems[selectedIndex] : null;
  const selectedCast = selected?.cast?.find((member) => member.id === selectedCastId)
    || selected?.cast?.[0]
    || null;

  useEffect(() => {
    const items = mode === "clips" ? batchFrames : data?.chapters;
    if (items?.length && !items.some((item) => item.id === selectedId)) {
      setSelectedId(items[0].id);
    }
  }, [batchFrames, data, mode, selectedId]);

  useEffect(() => {
    setSelectedCastId(selected?.cast?.[0]?.id || null);
  }, [selected?.id]);

  const register = useCallback((id, node) => {
    if (node) nodesRef.current.set(id, node);
    else nodesRef.current.delete(id);
  }, []);

  const nearestFrame = useCallback(() => {
    const rail = railRef.current;
    if (!rail || !reelItems.length) return null;
    const center = rail.getBoundingClientRect().top + rail.clientHeight / 2;
    let nearest = null;
    let distance = Infinity;
    for (const frame of reelItems) {
      const node = nodesRef.current.get(frame.id);
      if (!node) continue;
      const rect = node.getBoundingClientRect();
      const candidate = Math.abs(rect.top + rect.height / 2 - center);
      if (candidate < distance) {
        distance = candidate;
        nearest = frame;
      }
    }
    return nearest;
  }, [reelItems]);

  const stopMotion = useCallback(() => {
    cancelAnimationFrame(animationRef.current);
    momentumRef.current = false;
    velocityRef.current = 0;
  }, []);

  const animateToFrame = useCallback((frame) => {
    const rail = railRef.current;
    const node = nodesRef.current.get(frame?.id);
    if (!rail || !node) return;
    stopMotion();
    const start = rail.scrollTop;
    const target = node.offsetTop + node.offsetHeight / 2 - rail.clientHeight / 2;
    const delta = target - start;
    const duration = Math.min(900, Math.max(420, Math.abs(delta) * 0.7));
    const began = performance.now();

    const tick = (now) => {
      const progress = Math.min(1, (now - began) / duration);
      rail.scrollTop = start + delta * easeOutQuint(progress);
      if (progress < 1) animationRef.current = requestAnimationFrame(tick);
      else setSelectedId(frame.id);
    };
    animationRef.current = requestAnimationFrame(tick);
  }, [stopMotion]);

  const scheduleSnap = useCallback(() => {
    clearTimeout(snapTimerRef.current);
    snapTimerRef.current = setTimeout(() => {
      if (performance.now() - lastInputRef.current < 180) {
        scheduleSnap();
        return;
      }
      const frame = nearestFrame();
      if (frame) animateToFrame(frame);
    }, 220);
  }, [animateToFrame, nearestFrame]);

  const startMomentum = useCallback(() => {
    const rail = railRef.current;
    if (!rail) return;
    cancelAnimationFrame(animationRef.current);
    momentumRef.current = true;
    let previous = performance.now();

    const coast = (now) => {
      const elapsed = Math.min(34, now - previous);
      previous = now;
      const before = rail.scrollTop;
      rail.scrollTop += velocityRef.current * elapsed;
      const hitBoundary = rail.scrollTop === before && Math.abs(velocityRef.current) > 0.05;
      velocityRef.current *= Math.pow(hitBoundary ? 0.58 : 0.94, elapsed / 16.667);

      if (Math.abs(velocityRef.current) > 0.025) {
        animationRef.current = requestAnimationFrame(coast);
      } else {
        velocityRef.current = 0;
        momentumRef.current = false;
        scheduleSnap();
      }
    };
    animationRef.current = requestAnimationFrame(coast);
  }, [scheduleSnap]);

  const handleWheel = useCallback((event) => {
    event.preventDefault();
    lastInputRef.current = performance.now();
    cancelAnimationFrame(animationRef.current);
    momentumRef.current = true;
    velocityRef.current = Math.max(
      -5.5,
      Math.min(5.5, velocityRef.current + event.deltaY * 0.012)
    );
    startMomentum();
  }, [startMomentum]);

  const handlePointerDown = useCallback((event) => {
    if (event.button !== 0) return;
    stopMotion();
    lastInputRef.current = performance.now();
    const frameNode = event.target.closest?.("[data-frame-id]");
    dragRef.current = {
      active: true,
      y: event.clientY,
      time: performance.now(),
      moved: false,
      frameId: frameNode?.dataset.frameId || null
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.classList.add("is-dragging");
  }, [stopMotion]);

  const handlePointerMove = useCallback((event) => {
    const drag = dragRef.current;
    const rail = railRef.current;
    if (!drag.active || !rail) return;
    event.preventDefault();
    const now = performance.now();
    const delta = event.clientY - drag.y;
    const elapsed = Math.max(8, now - drag.time);
    rail.scrollTop -= delta;
    const instantaneousVelocity = -delta / elapsed;
    velocityRef.current = velocityRef.current * 0.62 + instantaneousVelocity * 0.38;
    drag.y = event.clientY;
    drag.time = now;
    drag.moved ||= Math.abs(delta) > 2;
    lastInputRef.current = now;
  }, []);

  const handlePointerEnd = useCallback((event) => {
    const drag = dragRef.current;
    if (!drag.active) return;
    drag.active = false;
    event.currentTarget.classList.remove("is-dragging");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }

    if (!drag.moved && drag.frameId) {
      const now = performance.now();
      const previous = clickRef.current;
      if (previous.frameId === drag.frameId && now - previous.time <= 450) {
        clickRef.current = { frameId: null, time: 0 };
        const frame = reelItems.find((item) => item.id === drag.frameId);
        if (frame) {
          animateToFrame(frame);
          return;
        }
      } else {
        clickRef.current = { frameId: drag.frameId, time: now };
      }
    }

    if (Math.abs(velocityRef.current) > 0.035) startMomentum();
    else scheduleSnap();
  }, [animateToFrame, reelItems, scheduleSnap, startMomentum]);

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const onScroll = () => {
      const frame = nearestFrame();
      if (frame) setSelectedId(frame.id);
      if (!dragRef.current.active && !momentumRef.current) scheduleSnap();
    };
    rail.addEventListener("wheel", handleWheel, { passive: false });
    rail.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      rail.removeEventListener("wheel", handleWheel);
      rail.removeEventListener("scroll", onScroll);
    };
  }, [handleWheel, nearestFrame, scheduleSnap]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (!reelItems.length || !["ArrowDown", "ArrowUp", "PageDown", "PageUp"].includes(event.key)) return;
      event.preventDefault();
      lastInputRef.current = performance.now();
      const direction = event.key.includes("Down") ? 1 : -1;
      const jump = event.key.startsWith("Page") ? 3 : 1;
      const nextIndex = Math.max(0, Math.min(reelItems.length - 1, selectedIndex + direction * jump));
      animateToFrame(reelItems[nextIndex]);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [animateToFrame, reelItems, selectedIndex]);

  useEffect(() => () => {
    clearTimeout(snapTimerRef.current);
    cancelAnimationFrame(animationRef.current);
  }, []);

  if (!data) {
    return <Box className="loading"><CircularProgress /><Typography>Threading the projector...</Typography></Box>;
  }

  const progress = stats.totalFrames
    ? (stats.completedFrames / stats.totalFrames) * 100
    : 0;

  return (
    <main className="app-shell">
      <header className="masthead">
        <Stack direction="row" spacing={1.5} alignItems="center">
          <MovieFilterIcon color="primary" />
          <div>
            <Typography variant="overline">CRADLE AI / LIVE CONTACT SHEET</Typography>
            <Typography variant="h1">The Colorization Reel</Typography>
          </div>
        </Stack>
        <nav className="view-tabs" aria-label="Content view">
          <div className={"clips-tab-menu" + (mode === "clips" ? " active" : "")}>
            <button
              type="button"
              className={mode === "clips" ? "active" : ""}
              onClick={() => setMode("clips")}
              aria-haspopup="menu"
            >
              Clips
            </button>
            {batches.length > 0 && (
              <div className="batch-submenu" role="menu" aria-label="Clip batches">
                {batches.map((batch) => (
                  <button
                    key={batch.batchName}
                    type="button"
                    role="menuitem"
                    className={activeBatch === batch.batchName ? "selected" : ""}
                    onClick={() => {
                      setMode("clips");
                      setSelectedBatch(batch.batchName);
                      setSelectedId(null);
                    }}
                    title={batch.batchTip}
                  >
                    <span>{batch.batchName}</span>
                    <small>{batch.batchTip}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            className={mode === "chapters" ? "active" : ""}
            onClick={() => setMode("chapters")}
          >
            Chapters
          </button>
          <button
            type="button"
            className={mode === "bookcast" ? "active" : ""}
            onClick={() => setMode("bookcast")}
          >
            Book Cast
          </button>
        </nav>
        <Stack className="status-block" spacing={0.7}>
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
            <FiberManualRecordIcon className="live-dot" />
            <Typography variant="caption">LIVE / 30 SEC</Typography>
            <Chip
              size="small"
              label={
                mode === "clips"
                  ? stats.completedImages + " renders"
                  : mode === "chapters"
                  ? data.stats.totalChapters + " chapters"
                  : (data.bookCast?.length || 0) + " cast"
              }
            />
          </Stack>
          <LinearProgress variant="determinate" value={progress} />
          <Typography variant="caption" color="text.secondary">
            {mode === "clips"
              ? `${stats.completedFrames} of ${stats.totalFrames} frames developed`
              : mode === "chapters"
              ? `${data.stats.chaptersWithCast} chapters with cast metadata`
              : `${data.stats?.bookCastWithImages || 0} of ${data.bookCast?.length || 0} cast with renders`}
          </Typography>
        </Stack>
      </header>

      {error && <div className="connection-error">{error}</div>}

      <section className="workspace">
        {mode === "bookcast" ? (
          <BookCastView
            bookCast={data.bookCast || []}
            onExpandImage={(img) => setExpandedImage(img)}
          />
        ) : (
          <>
            <div className="reel-column">
          <div className="focus-marker">
            <span>{mode === "clips" ? "CURRENT FRAME" : "CURRENT CHAPTER"}</span>
            <b>{selected?.label || "---"}</b>
          </div>
          {mode === "clips" && activeBatch && (
            <div className="batch-context">
              <span>{activeBatch}</span>
              <small>{batches.find((batch) => batch.batchName === activeBatch)?.batchTip}</small>
            </div>
          )}
          <div
            className="film-rail"
            ref={railRef}
            tabIndex={0}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerEnd}
            onPointerCancel={handlePointerEnd}
          >
            <div className="film-stock">
              <div className="leader leader-top">CRADLE / 35 MM / 2026</div>
              {reelItems.map((frame) => (
                <FilmFrame
                  key={frame.id}
                  frame={frame}
                  selected={frame.id === selectedId}
                  register={register}
                />
              ))}
              <div className="leader leader-bottom">END OF REEL</div>
            </div>
          </div>
        </div>

        <aside className="inspector">
          <div className="selection-title">
            <div>
              <Typography variant="overline">NOW PROJECTING</Typography>
              <Typography variant="h2">{selected?.label}</Typography>
            </div>
            {mode === "clips" ? (
              <div className="score-readout">
                <span>BEST MATCH</span>
                <strong>{selected?.bestSimilarity == null ? "--" : selected.bestSimilarity.toFixed(2) + "%"}</strong>
              </div>
            ) : (
              <div className="score-readout">
                <span>MOVIE RANGE</span>
                <strong className="chapter-range">{selected?.movieStartTimecode}</strong>
              </div>
            )}
          </div>

          {mode === "clips" ? (
            <div className={
              "clip-presentation" + (clipDescriptionOpen ? " is-description-open" : "")
            }>
              <Theater frame={selected} />
              <Paper className="clip-description-card" elevation={0}>
                <button
                  type="button"
                  className="clip-description-toggle"
                  aria-expanded={clipDescriptionOpen}
                  aria-label={
                    clipDescriptionOpen
                      ? "Collapse clip description"
                      : "Expand clip description"
                  }
                  onClick={() => setClipDescriptionOpen((current) => !current)}
                >
                  {clipDescriptionOpen ? <ChevronRightIcon /> : <ChevronLeftIcon />}
                  <span>DESCRIPTION</span>
                </button>
                <div className="clip-description-content" aria-hidden={!clipDescriptionOpen}>
                  <Typography variant="overline">Clip Description</Typography>
                  <Typography variant="body2">
                    {selected?.clipDescription || "No clip description available."}
                  </Typography>
                </div>
              </Paper>
            </div>
          ) : (
            <Theater frame={selected} />
          )}

          {mode === "clips" ? (
            <>
              <div className="gallery-heading">
                <Typography variant="h2">Frame Variations</Typography>
                <Typography variant="body2" color="text.secondary">
                  Original negative plus ten developed candidates, ordered by generation.
                </Typography>
              </div>
              <div className="gallery-grid">
                {selected && (
                  <GalleryTile title="FRAME 0" url={selected.originalUrl} original />
                )}
                {selected?.generations.map((generation) => (
                  <GalleryTile
                    key={generation.sequence}
                    title={"GEN " + generation.sequence}
                    url={generation.url}
                    similarity={generation.similarity}
                    best={generation.sequence === selected.bestSequence}
                    onExpand={generation.url ? () => setExpandedImage({
                      url: generation.url,
                      title: "Generation " + generation.sequence,
                      similarity: generation.similarity
                    }) : undefined}
                  />
                ))}
              </div>
              <Paper className="info-card prompt-card frame-prompt-card" elevation={0}>
                <Typography variant="overline">Prompt Text</Typography>
                <Typography className="prompt-text" variant="body2">
                  {selected?.promptText || "No prompt text available."}
                </Typography>
              </Paper>
            </>
          ) : (
            <>
              <div className="chapter-copy-grid">
                <Paper className="info-card" elevation={0}>
                  <Typography variant="overline">Chapter Summary</Typography>
                  <Typography className="chapter-summary" variant="body2">
                    {selected?.chapterSummary || "No summary available."}
                  </Typography>
                </Paper>
                <Paper className="info-card" elevation={0}>
                  <Typography variant="overline">Chapter Transcript</Typography>
                  <div className="chapter-transcript">
                    {selected?.transcript?.map((turn, index) => (
                      <p key={index}>
                        <strong>{turn.speaker}</strong>
                        <span>{turn.text}</span>
                      </p>
                    ))}
                  </div>
                </Paper>
              </div>

              <div className="gallery-heading cast-heading">
                <Typography variant="h2">Chapter Cast</Typography>
                <Typography variant="body2" color="text.secondary">
                  Select a cast reference to inspect its grounded character design.
                </Typography>
              </div>
              <div className="cast-carousel">
                {selected?.cast?.map((member) => {
                  const generations = member.imageGenerations || [];
                  const generationIndex = Math.min(
                    castGenerationIndexes[member.id] || 0,
                    Math.max(0, generations.length - 1)
                  );
                  const generation = generations[generationIndex];
                  return (
                    <div
                      key={member.id}
                      className={"cast-slide" + (member.id === selectedCast?.id ? " active" : "")}
                    >
                      <div className="cast-image-stage">
                        <button
                          type="button"
                          className="cast-image-button"
                          onClick={() => setSelectedCastId(member.id)}
                          onDoubleClick={() => {
                            if (generation?.imageUrl) {
                              setExpandedImage({
                                url: generation.imageUrl,
                                title: member.characterName,
                                caption: generation.genaimodel,
                                fullWindow: true
                              });
                            }
                          }}
                        >
                          {generation?.imageUrl ? (
                            <img
                              src={generation.imageUrl}
                              alt={member.characterName}
                              loading="lazy"
                            />
                          ) : (
                            <div className="cast-placeholder">
                              <span>{member.characterName?.slice(0, 1) || "?"}</span>
                              IMAGE PENDING
                            </div>
                          )}
                        </button>
                        {generation?.genaimodel && (
                          <span className="cast-model-watermark">
                            {generation.genaimodel}
                          </span>
                        )}
                        {generations.length > 0 && (
                          <nav
                            className="cast-generation-dots"
                            aria-label={`${member.characterName} image variants`}
                          >
                            {generations.map((candidate, index) => (
                              <button
                                type="button"
                                key={`${candidate.genaimodel}-${index}`}
                                className={index === generationIndex ? "active" : ""}
                                aria-label={`Show ${candidate.genaimodel} image`}
                                aria-pressed={index === generationIndex}
                                onClick={() => {
                                  setSelectedCastId(member.id);
                                  setCastGenerationIndexes((current) => ({
                                    ...current,
                                    [member.id]: index
                                  }));
                                }}
                              />
                            ))}
                          </nav>
                        )}
                      </div>
                      <b>{member.characterName}</b>
                      {generation?.celebrityName && (
                        <span className="cast-celebrity-name">
                          {generation.celebrityName}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="character-card-grid">
                <div className="character-card-column">
                  <Paper className="info-card character-card" elevation={0}>
                    <Typography variant="overline">Character Description</Typography>
                    <Typography variant="h3">{selectedCast?.characterName || "No cast selected"}</Typography>
                    <Typography className="character-description" variant="body2">
                      {selectedCast?.characterDescription || "No character description available."}
                    </Typography>
                  </Paper>
                  <Paper className="info-card character-card prompt-card" elevation={0}>
                    <Typography variant="overline">Generated Prompt Text</Typography>
                    <Typography className="prompt-text" variant="body2">
                      {selectedCast?.characterGenprompt || "No generated prompt text available."}
                    </Typography>
                  </Paper>
                </div>
                <Paper className="info-card character-card" elevation={0}>
                  <Typography variant="overline">Character Details</Typography>
                  <CharacterDetails details={selectedCast?.characterDetails} />
                </Paper>
              </div>
            </>
          )}
        </aside>
          </>
        )}
      </section>

      <Dialog
        open={Boolean(expandedImage)}
        onClose={() => setExpandedImage(null)}
        maxWidth={false}
        PaperProps={{
          className:
            "image-lightbox" + (expandedImage?.fullWindow ? " full-window" : "")
        }}
      >
        <IconButton
          className="lightbox-close"
          onClick={() => setExpandedImage(null)}
          aria-label="Close expanded image"
        >
          <CloseIcon />
        </IconButton>
        {expandedImage && (
          <>
            <img
              src={expandedImage.url}
              alt={expandedImage.title}
              onClick={() => setExpandedImage(null)}
            />
            <div className="lightbox-caption">
              <Typography>{expandedImage.title}</Typography>
              <Typography color="primary">
                {expandedImage.caption
                  ? expandedImage.caption
                  : expandedImage.similarity == null
                  ? "Score pending"
                  : expandedImage.similarity.toFixed(2) + "% similarity"}
              </Typography>
            </div>
          </>
        )}
      </Dialog>
    </main>
  );
}
