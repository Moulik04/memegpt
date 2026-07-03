"use client";

interface Props {
  message: string;
}

export function ThinkingBubble({ message }: Props) {
  return (
    <div className="flex justify-start mb-4">
      <div className="rounded-2xl rounded-bl-sm bg-[#13131e] border border-gray-800/60
                      px-4 py-3 shadow flex items-center gap-2.5">
        <span className="w-2 h-2 rounded-full bg-brand-400 dot-1 block" />
        <span className="w-2 h-2 rounded-full bg-brand-400 dot-2 block" />
        <span className="w-2 h-2 rounded-full bg-brand-400 dot-3 block" />
        <span className="text-gray-500 text-xs italic ml-1">{message}</span>
      </div>
    </div>
  );
}
