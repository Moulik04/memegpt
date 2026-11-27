import type { Metadata } from "next";
import { LoreView } from "@/components/LoreView";
import { Masthead } from "@/components/Masthead";
import { MobileNav } from "@/components/MobileNav";

export const metadata: Metadata = {
  title: "Lore",
  description: "Paste a whole group chat or drop in screenshots. Get back several memes, one for every moment worth remembering.",
};

export default function LorePage() {
  return (
    <div className="flex flex-col h-full">
      <Masthead variant="app" active="lore" history />
      <LoreView />
      <MobileNav active="lore" />
    </div>
  );
}
