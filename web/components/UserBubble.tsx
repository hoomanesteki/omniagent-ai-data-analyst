export function UserBubble({ question }: { question: string }) {
  return (
    <div className="flex justify-end">
      <div className="animate-turn-in max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-[15px] leading-6 text-primary-foreground">
        {question}
      </div>
    </div>
  );
}
