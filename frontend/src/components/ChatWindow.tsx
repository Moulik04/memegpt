"use client";

import { useEffect, useRef, useState } from "react";
import { sendChat } from "@/lib/api";
import { MessageBubble } from "./MessageBubble";
import type { ChatMessage } from "@/types";

export function ChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await sendChat(text, conversationId);
      setConversationId(res.conversation_id);
      setMessages((prev) => [...prev, res.message]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col w-full max-w-2xl h-[70vh] bg-gray-900 rounded-2xl border border-gray-700 shadow-2xl">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 chat-scroll">
        {messages.length === 0 && (
          <p className="text-center text-gray-600 text-sm mt-8">
            Say anything — I&apos;ll reply in memes.
          </p>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}
        {loading && (
          <div className="flex justify-start mb-3">
            <div className="bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-400 animate-pulse">
              Generating meme...
            </div>
          </div>
        )}
        {error && (
          <p className="text-center text-red-400 text-xs mt-2">{error}</p>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 p-3 border-t border-gray-700"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={loading}
          className="flex-1 bg-gray-800 rounded-xl px-4 py-2.5 text-sm placeholder-gray-500
                     focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-40 transition-colors
                     text-white text-sm font-semibold rounded-xl px-4 py-2.5"
        >
          Send
        </button>
      </form>
    </div>
  );
}
