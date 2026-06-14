"use client";

import { MemeDisplay } from "./MemeDisplay";
import type { ChatMessage } from "@/types";

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow
          ${isUser
            ? "bg-brand-600 text-white rounded-br-sm"
            : "bg-gray-800 text-gray-100 rounded-bl-sm"
          }`}
      >
        {message.content && <p>{message.content}</p>}
        {message.meme_url && (
          <MemeDisplay url={message.meme_url} alt={message.content} />
        )}
      </div>
    </div>
  );
}
