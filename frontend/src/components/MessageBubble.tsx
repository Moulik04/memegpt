"use client";

import { useRef, useState } from "react";
import { MemeDisplay } from "./MemeDisplay";
import { MemeCard } from "./MemeCard";
import { FeedbackButtons } from "./FeedbackButtons";
import { ShareButtons } from "./ShareButtons";
import type { ChatMessage, MemeItem } from "@/types";

interface Props {
  message: ChatMessage;
  onFeedback?: (meme: MemeItem, rating: "up" | "down") => void;
}

export function MessageBubble({ message, onFeedback }: Props) {
  const isUser = message.role === "user";
  const [activeIndex, setActiveIndex] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  if (isUser) {
    const images = message.userImages ?? [];
    return (
      <div className="flex justify-end mb-3">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed
                        bg-gradient-to-br from-brand-700 to-brand-600 text-white shadow-lg shadow-brand-900/30">
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

  function handleScroll() {
    const el = scrollRef.current;
    if (!el || el.clientWidth === 0) return;
    const index = Math.round(el.scrollLeft / el.clientWidth);
    setActiveIndex(Math.max(0, Math.min(index, memes.length - 1)));
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] sm:max-w-[75%]">
        {memes.length === 0 && (
          /* Plain text bot message */
          <div className="rounded-2xl rounded-bl-sm bg-[#13131e] border border-gray-800/60
                          px-4 py-2.5 text-sm leading-relaxed text-gray-100 shadow">
            {message.content}
          </div>
        )}

        {memes.length === 1 && (
          /* Single meme — same layout as before multi-meme support existed */
          <MemeCard
            url={memes[0].url}
            alt={memes[0].situationText}
            onFeedback={onFeedback ? (rating) => onFeedback(memes[0], rating) : undefined}
          />
        )}

        {memes.length > 1 && (
          /* iMessage-style: several memes from one submission, one bubble,
             swipe/scroll left-right through them */
          <div className="rounded-2xl rounded-bl-sm bg-[#13131e] border border-gray-800/60
                          p-3 shadow-lg">
            <div
              ref={scrollRef}
              onScroll={handleScroll}
              className="flex overflow-x-auto snap-x snap-mandatory gap-2 chat-scroll"
            >
              {memes.map((meme, i) => (
                <div key={i} className="shrink-0 w-full snap-center">
                  <MemeDisplay url={meme.url} alt={meme.situationText} />
                </div>
              ))}
            </div>

            <div className="flex items-center justify-center gap-1 mt-2">
              {memes.map((_, i) => (
                <span
                  key={i}
                  className={`w-1.5 h-1.5 rounded-full transition-colors ${
                    i === activeIndex ? "bg-brand-500" : "bg-gray-700"
                  }`}
                />
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
