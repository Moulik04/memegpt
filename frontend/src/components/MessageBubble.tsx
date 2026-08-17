"use client";

import { useEffect, useRef, useState } from "react";
import { animate, motion, useMotionValue, type PanInfo } from "motion/react";
import { MemeDisplay } from "./MemeDisplay";
import { MemeCard } from "./MemeCard";
import { FeedbackButtons } from "./FeedbackButtons";
import { ShareButtons } from "./ShareButtons";
import { DecryptedText } from "./DecryptedText";
import type { ChatMessage, MemeItem } from "@/types";

interface Props {
  message: ChatMessage;
  onFeedback?: (meme: MemeItem, rating: "up" | "down") => void;
}

export function MessageBubble({ message, onFeedback }: Props) {
  const isUser = message.role === "user";
  const [activeIndex, setActiveIndex] = useState(0);
  // Real width, not a percentage — dragging manipulates `x` in pixels, and
  // mixing percentage-based positioning with a px-based drag delta doesn't
  // track correctly. Measured via ResizeObserver since the bubble's width
  // depends on its container (max-w-[85%] etc.), not a fixed value.
  const trackWrapRef = useRef<HTMLDivElement>(null);
  const [trackWidth, setTrackWidth] = useState(0);

  useEffect(() => {
    const el = trackWrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setTrackWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // All slides stay mounted (the drag track needs them side by side), and a
  // flex row's natural height defaults to its TALLEST child — without this,
  // the card stays sized to the tallest meme even while showing a shorter
  // one. Track just the active slide's real height and apply it to the
  // wrapper directly, so the card actually fits what's showing.
  const slideRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const [activeHeight, setActiveHeight] = useState<number | undefined>(undefined);

  useEffect(() => {
    const el = slideRefs.current.get(activeIndex);
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setActiveHeight(entry.contentRect.height));
    observer.observe(el);
    return () => observer.disconnect();
  }, [activeIndex]);

  // A plain motion value driven imperatively, NOT the declarative `animate`
  // prop — `drag` + a declarative `animate={{ x }}` on the same element is
  // a documented Motion conflict: the animate prop re-asserts its target
  // on every render and fights a live drag gesture, so drag never visibly
  // moves anything. Snapping to a new index re-animates this value in the
  // effect below instead.
  const trackX = useMotionValue(0);

  useEffect(() => {
    const controls = animate(trackX, -activeIndex * trackWidth, {
      type: "spring",
      stiffness: 300,
      damping: 32,
    });
    return () => controls.stop();
  }, [activeIndex, trackWidth, trackX]);

  if (isUser) {
    const images = message.userImages ?? [];
    return (
      <div className="flex justify-end mb-3">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed
                        bg-secondary text-secondary-foreground shadow-lg">
          {images.length > 0 && (
            <div className={`flex flex-wrap gap-1.5 ${message.content ? "mb-2" : ""}`}>
              {images.map((src, i) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={i}
                  src={src}
                  alt="Your uploaded photo"
                  className="rounded-xl max-h-48 object-cover"
                  style={{ maxWidth: images.length > 1 ? "45%" : "100%" }}
                />
              ))}
            </div>
          )}
          {message.content && <div>{message.content}</div>}
        </div>
      </div>
    );
  }

  const memes = message.memes ?? [];

  // Real drag physics instead of raw CSS scroll-snap: dragging past ~20% of
  // the track width, or flicking past a velocity threshold, advances one
  // slide — otherwise it springs back. dragElastic gives resistance at the
  // ends instead of a hard stop.
  function handleDragEnd(_event: unknown, info: PanInfo) {
    const OFFSET_THRESHOLD = trackWidth * 0.2;
    const VELOCITY_THRESHOLD = 400;
    if (info.offset.x < -OFFSET_THRESHOLD || info.velocity.x < -VELOCITY_THRESHOLD) {
      setActiveIndex((i) => Math.min(memes.length - 1, i + 1));
    } else if (info.offset.x > OFFSET_THRESHOLD || info.velocity.x > VELOCITY_THRESHOLD) {
      setActiveIndex((i) => Math.max(0, i - 1));
    }
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] sm:max-w-[75%]">
        {memes.length === 0 && (
          /* Plain text bot message */
          <div className="rounded-2xl rounded-bl-sm bg-card border border-border
                          px-4 py-2.5 text-sm leading-relaxed text-gray-100 shadow">
            <DecryptedText text={message.content} />
          </div>
        )}

        {memes.length === 1 && (
          /* Single meme — same layout as before multi-meme support existed */
          <MemeCard
            url={memes[0].url}
            alt={memes[0].situationText}
            templateId={memes[0].templateId}
            onFeedback={onFeedback ? (rating) => onFeedback(memes[0], rating) : undefined}
          />
        )}

        {memes.length > 1 && (
          /* iMessage-style: several memes from one submission, one bubble,
             swipe/scroll left-right through them. Real drag physics
             (elastic resistance + velocity-based advance) instead of raw
             CSS scroll-snap, and a shared-element (layoutId) dot indicator
             that slides between positions instead of just recoloring. */
          <div className="rounded-2xl rounded-bl-sm bg-card border border-border
                          p-3 shadow-lg">
            <div
              ref={trackWrapRef}
              className="overflow-hidden rounded-xl transition-[height] duration-300 ease-out"
              style={activeHeight ? { height: activeHeight } : undefined}
            >
              <motion.div
                className="flex items-start"
                style={{ x: trackX }}
                drag={trackWidth > 0 ? "x" : false}
                dragConstraints={{ left: -(trackWidth * (memes.length - 1)), right: 0 }}
                dragElastic={0.15}
                onDragEnd={handleDragEnd}
              >
                {memes.map((meme, i) => (
                  <div
                    key={i}
                    className="shrink-0"
                    style={{ width: trackWidth || "100%" }}
                  >
                    <div
                      className="px-0.5"
                      ref={(el) => {
                        if (el) slideRefs.current.set(i, el);
                        else slideRefs.current.delete(i);
                      }}
                    >
                      <MemeDisplay url={meme.url} alt={meme.situationText} />
                    </div>
                  </div>
                ))}
              </motion.div>
            </div>

            <div className="flex items-center justify-center gap-1.5 mt-2">
              {memes.map((_, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setActiveIndex(i)}
                  aria-label={`Meme ${i + 1} of ${memes.length}`}
                  aria-current={i === activeIndex}
                  className="relative w-1.5 h-1.5 rounded-full bg-gray-700 cursor-pointer"
                >
                  {i === activeIndex && (
                    <motion.span
                      layoutId="active-meme-dot"
                      className="absolute inset-0 rounded-full bg-accent"
                      transition={{ type: "spring", stiffness: 500, damping: 35 }}
                    />
                  )}
                </button>
              ))}
            </div>

            <div className="flex items-center justify-between mt-2">
              <ShareButtons memeUrl={memes[activeIndex].url} />
              {onFeedback && (
                <FeedbackButtons
                  key={activeIndex}
                  onFeedback={(rating) => onFeedback(memes[activeIndex], rating)}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
