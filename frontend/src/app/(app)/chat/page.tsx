import type { Metadata } from "next";
import { ChatWindow } from "@/components/ChatWindow";
import { Masthead } from "@/components/Masthead";
import { MobileNav } from "@/components/MobileNav";

export const metadata: Metadata = {
  title: "Chat",
  description: "Talk to MemeGPT like any chatbot. Every reply comes back as a meme.",
};

export default function ChatPage() {
  return (
    <div className="flex flex-col h-full">
      <Masthead variant="app" active="chat" history />
      <ChatWindow />

      <MobileNav active="chat" />
    </div>
  );
}
