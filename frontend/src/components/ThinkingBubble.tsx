"use client";

interface Props {
  message: string;
}

export function ThinkingBubble({ message }: Props) {
  return (
    <div className="flex justify-start mb-4">
      <div className="rounded-2xl rounded-bl-sm bg-card border border-border
                      px-4 py-3 shadow flex items-center gap-2.5">
        <span className="thinking-orb block" />
        <span className="text-gray-500 text-xs italic ml-1">{message}</span>
      </div>
    </div>
  );
}
