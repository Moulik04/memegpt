"use client";

interface Props {
  message: string;
}

export function ThinkingBubble({ message }: Props) {
  return (
    <div className="flex justify-start mb-4">
      <div className="rounded-2xl rounded-bl-sm bg-card border border-border
                      px-4 py-3 shadow flex items-center gap-2.5">
        <span className="w-2 h-2 rounded-full bg-accent dot-1 block" />
        <span className="w-2 h-2 rounded-full bg-accent dot-2 block" />
        <span className="w-2 h-2 rounded-full bg-accent dot-3 block" />
        <span className="text-gray-500 text-xs italic ml-1">{message}</span>
      </div>
    </div>
  );
}
