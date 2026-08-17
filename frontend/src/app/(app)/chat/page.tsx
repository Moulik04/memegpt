import { ChatWindow } from "@/components/ChatWindow";
import { ModeTabs } from "@/components/ModeTabs";
import { MobileNav } from "@/components/MobileNav";

export default function ChatPage() {
  return (
    <div className="flex flex-col h-full">
      <ModeTabs active="chat" />

      {/* Chat fills remaining height */}
      <div className="flex-1 min-h-0 flex flex-col max-w-2xl w-full mx-auto">
        <ChatWindow />
      </div>

      <MobileNav active="chat" />
    </div>
  );
}
