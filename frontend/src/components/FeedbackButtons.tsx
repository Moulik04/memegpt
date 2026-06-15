"use client";

import { useState } from "react";

interface Props {
  onFeedback: (rating: "up" | "down") => void;
}

export function FeedbackButtons({ onFeedback }: Props) {
  const [voted, setVoted] = useState<"up" | "down" | null>(null);

  function handleVote(rating: "up" | "down") {
    if (voted) return;
    setVoted(rating);
    onFeedback(rating);
  }

  return (
    <div className="flex gap-1 mt-2 justify-end">
      <button
        onClick={() => handleVote("up")}
        disabled={!!voted}
        title="Good meme"
        className={`text-base px-1.5 py-0.5 rounded transition-all duration-200 ${
          voted === "up"
            ? "opacity-100 scale-110"
            : voted
            ? "opacity-20 cursor-not-allowed"
            : "opacity-40 hover:opacity-90 hover:scale-110 cursor-pointer"
        }`}
      >
        👍
      </button>
      <button
        onClick={() => handleVote("down")}
        disabled={!!voted}
        title="Bad meme"
        className={`text-base px-1.5 py-0.5 rounded transition-all duration-200 ${
          voted === "down"
            ? "opacity-100 scale-110"
            : voted
            ? "opacity-20 cursor-not-allowed"
            : "opacity-40 hover:opacity-90 hover:scale-110 cursor-pointer"
        }`}
      >
        👎
      </button>
    </div>
  );
}
