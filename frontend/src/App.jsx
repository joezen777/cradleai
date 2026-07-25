import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Chip,
  CircularProgress,
  LinearProgress,
  Paper,
  Stack,
  Typography
} from "@mui/material";
import MovieFilterIcon from "@mui/icons-material/MovieFilter";
import FiberManualRecordIcon from "@mui/icons-material/FiberManualRecord";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";

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
          {frame.bestSimilarity == null
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

function GalleryTile({ title, url, similarity, original, best }) {
  return (
    <Paper className={"gallery-tile" + (best ? " best" : "")} elevation={0}>
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

export default function App() {
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState("");
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
      const response = await fetch("/api/state", { cache: "no-store" });
      if (!response.ok) throw new Error("Monitor API returned " + response.status);
      const next = await response.json();
      setData(next);
      setSelectedId((current) => current || next.frames[0]?.id || null);
      setError("");
    } catch (reason) {
      setError(reason.message);
    }
  }, []);

  useEffect(() => {
    loadState();
    const events = new EventSource("/api/events");
    events.addEventListener("update", loadState);
    events.onerror = () => setError("Live connection interrupted; retrying...");
    return () => events.close();
  }, [loadState]);

  const selectedIndex = useMemo(
    () => data?.frames.findIndex((frame) => frame.id === selectedId) ?? -1,
    [data, selectedId]
  );
  const selected = selectedIndex >= 0 ? data.frames[selectedIndex] : null;

  const register = useCallback((id, node) => {
    if (node) nodesRef.current.set(id, node);
    else nodesRef.current.delete(id);
  }, []);

  const nearestFrame = useCallback(() => {
    const rail = railRef.current;
    if (!rail || !data?.frames.length) return null;
    const center = rail.getBoundingClientRect().top + rail.clientHeight / 2;
    let nearest = null;
    let distance = Infinity;
    for (const frame of data.frames) {
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
  }, [data]);

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
        const frame = data?.frames.find((item) => item.id === drag.frameId);
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
  }, [animateToFrame, data, scheduleSnap, startMomentum]);

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
      if (!data?.frames.length || !["ArrowDown", "ArrowUp", "PageDown", "PageUp"].includes(event.key)) return;
      event.preventDefault();
      lastInputRef.current = performance.now();
      const direction = event.key.includes("Down") ? 1 : -1;
      const jump = event.key.startsWith("Page") ? 3 : 1;
      const nextIndex = Math.max(0, Math.min(data.frames.length - 1, selectedIndex + direction * jump));
      animateToFrame(data.frames[nextIndex]);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [animateToFrame, data, selectedIndex]);

  useEffect(() => () => {
    clearTimeout(snapTimerRef.current);
    cancelAnimationFrame(animationRef.current);
  }, []);

  if (!data) {
    return <Box className="loading"><CircularProgress /><Typography>Threading the projector...</Typography></Box>;
  }

  const progress = data.stats.totalFrames
    ? (data.stats.completedFrames / data.stats.totalFrames) * 100
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
        <Stack className="status-block" spacing={0.7}>
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
            <FiberManualRecordIcon className="live-dot" />
            <Typography variant="caption">LIVE / 30 SEC</Typography>
            <Chip size="small" label={data.stats.completedImages + " renders"} />
          </Stack>
          <LinearProgress variant="determinate" value={progress} />
          <Typography variant="caption" color="text.secondary">
            {data.stats.completedFrames} of {data.stats.totalFrames} frames developed
          </Typography>
        </Stack>
      </header>

      {error && <div className="connection-error">{error}</div>}

      <section className="workspace">
        <div className="reel-column">
          <div className="focus-marker">
            <span>CURRENT FRAME</span>
            <b>{selected?.label || "---"}</b>
          </div>
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
              {data.frames.map((frame) => (
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
            <div className="score-readout">
              <span>BEST MATCH</span>
              <strong>{selected?.bestSimilarity == null ? "--" : selected.bestSimilarity.toFixed(2) + "%"}</strong>
            </div>
          </div>

          <Theater frame={selected} />

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
              />
            ))}
          </div>
        </aside>
      </section>
    </main>
  );
}
