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
    <div className="flex gap-0.5">
      <button
        onClick={() => handleVote("up")}
        disabled={!!voted}
        title="Good meme"
        className={`action-btn text-base px-1.5 py-0.5 ${
          voted === "up"
            ? "opacity-100"
            : voted
            ? "opacity-20 cursor-not-allowed"
            : ""
        }`}
      >
        👍
      </button>
      <button
        onClick={() => handleVote("down")}
        disabled={!!voted}
        title="Bad meme"
        className={`action-btn text-base px-1.5 py-0.5 ${
          voted === "down"
            ? "opacity-100"
            : voted
            ? "opacity-20 cursor-not-allowed"
            : ""
        }`}
      >
        👎
      </button>
    </div>
  );
}
