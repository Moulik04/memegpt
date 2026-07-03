"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { postFeedback, sendChatStream } from "@/lib/api";
import { FeedbackButtons } from "./FeedbackButtons";
import { MessageBubble } from "./MessageBubble";
import { ThinkingBubble } from "./ThinkingBubble";
import type { ChatMessage } from "@/types";

const EXAMPLE_PROMPTS = [
  "waiting for my PR to get reviewed for 3 days",
  "my plan was going great then suddenly it wasn't",
  "me vs my alarm clock at 7am",
  "when the deploy finally works on first try",
  "my friend after 4 drinks claiming he's sober",
  "my manager asking who broke production",
];

interface ThinkingState { message: string }

export function ChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [thinking, setThinking] = useState<ThinkingState | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  const handleFeedback = useCallback(
    async (messageIndex: number, rating: "up" | "down") => {
      const msg = messages[messageIndex];
      if (!msg || msg.role !== "assistant") return;
      const userMsg = messages.slice(0, messageIndex).reverse().find((m) => m.role === "user");
      await postFeedback({
        conversation_id: conversationId,
        template_id: msg.template_id || "",
        texts: {},
        rating,
        user_message: userMsg?.content,
      }).catch(() => {});
    },
    [messages, conversationId],
  );

  async function submit(text: string) {
    if (!text.trim() || loading) return;
    const userMsg: ChatMessage = {
      role: "user",
      content: text.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);
    setThinking({ message: "Reading your vibe…" });
    try {
      await sendChatStream(text.trim(), conversationId, (event) => {
        if (event.type === "thinking") {
          setThinking({ message: event.message });
        } else if (event.type === "done") {
          setThinking(null);
          setConversationId(event.conversation_id);
          setMessages((prev) => [
            ...prev,
            { ...event.message, template_id: event.template_used },
          ]);
        } else if (event.type === "error") {
          setError(event.message);
          setThinking(null);
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
      setThinking(null);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(input);
  }

  function handlePromptChip(prompt: string) {
    setInput(prompt);
    inputRef.current?.focus();
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
        {messages.length === 0 && !thinking && (
          <div className="flex flex-col items-center justify-center h-full gap-6 py-8">
            <div className="text-center">
              <p className="text-gray-500 text-sm">Say anything — I&apos;ll reply in memes.</p>
              <p className="text-gray-600 text-xs mt-1">Or pick a prompt below ↓</p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center max-w-sm">
              {EXAMPLE_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => handlePromptChip(p)}
                  className="prompt-chip"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            onFeedback={
              msg.role === "assistant" && msg.meme_url
                ? (rating) => handleFeedback(i, rating)
                : undefined
            }
          />
        ))}

        {thinking && <ThinkingBubble message={thinking.message} />}

        {error && (
          <div className="flex justify-start mb-3">
            <p className="text-red-400 text-xs bg-red-900/20 border border-red-800/40
                          rounded-xl px-3 py-2 max-w-[80%]">
              {error}
            </p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="shrink-0 border-t border-gray-800/60 px-3 py-3">
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message…"
            disabled={loading}
            className="flex-1 bg-[#13131e] border border-gray-800 rounded-xl px-4 py-2.5
                       text-sm placeholder-gray-600 focus:outline-none focus:border-brand-600
                       disabled:opacity-50 transition-colors"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-brand-600 hover:bg-brand-700 disabled:opacity-40 transition-colors
                       text-white text-sm font-semibold rounded-xl px-4 py-2.5 shrink-0"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
