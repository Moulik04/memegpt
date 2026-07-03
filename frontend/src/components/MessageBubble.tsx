"use client";

import { MemeDisplay } from "./MemeDisplay";
import { FeedbackButtons } from "./FeedbackButtons";
import { ShareButtons } from "./ShareButtons";
import type { ChatMessage } from "@/types";

interface Props {
  message: ChatMessage;
  onFeedback?: (rating: "up" | "down") => void;
}

function templateLabel(id?: string) {
  if (!id) return null;
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function MessageBubble({ message, onFeedback }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end mb-3">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed
                        bg-gradient-to-br from-brand-700 to-brand-600 text-white shadow-lg shadow-brand-900/30">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] sm:max-w-[75%]">
        {/* Meme card */}
        {message.meme_url ? (
          <div className="rounded-2xl rounded-bl-sm bg-[#13131e] border border-gray-800/60
                          p-3 shadow-lg">
            <MemeDisplay url={message.meme_url} alt={message.content} />

            {/* Template badge */}
            {message.template_id && (
              <p className="text-[10px] text-gray-600 mt-2 px-0.5">
                {templateLabel(message.template_id)}
              </p>
            )}

            {/* Action row: share left, feedback right */}
            <div className="flex items-center justify-between mt-1">
              <ShareButtons memeUrl={message.meme_url} />
              {onFeedback && <FeedbackButtons onFeedback={onFeedback} />}
            </div>
          </div>
        ) : (
          /* Plain text bot message */
          <div className="rounded-2xl rounded-bl-sm bg-[#13131e] border border-gray-800/60
                          px-4 py-2.5 text-sm leading-relaxed text-gray-100 shadow">
            {message.content}
          </div>
        )}
      </div>
    </div>
  );
}
