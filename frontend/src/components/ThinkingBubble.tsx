"use client";

interface Props {
  message: string;
}

export function ThinkingBubble({ message }: Props) {
  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[75%] bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-3 shadow">
        <div className="flex items-center gap-2.5">
          {/* Three bouncing dots */}
          <span
            className="block w-2 h-2 rounded-full bg-purple-400"
            style={{ animation: "bounce 1.2s infinite", animationDelay: "0ms" }}
          />
          <span
            className="block w-2 h-2 rounded-full bg-purple-400"
            style={{ animation: "bounce 1.2s infinite", animationDelay: "200ms" }}
          />
          <span
            className="block w-2 h-2 rounded-full bg-purple-400"
            style={{ animation: "bounce 1.2s infinite", animationDelay: "400ms" }}
          />
          <span className="text-gray-400 text-xs italic ml-1">{message}</span>
        </div>
      </div>
    </div>
  );
}
