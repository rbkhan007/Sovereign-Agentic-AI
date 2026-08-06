export default function Loading() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]" role="status" aria-label="Loading">
      <div className="flex flex-col items-center gap-5">
        <div className="relative w-14 h-14">
          <div className="absolute inset-0 rounded-full border-2 border-accent/15" />
          <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-accent border-r-accent/40 animate-spin" />
          <div className="absolute inset-2 rounded-full border border-accent/20 animate-pulse" />
        </div>
        <div className="flex flex-col items-center gap-2">
          <div className="flex gap-1.5">
            <span className="w-2 h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-accent-2 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-accent-3 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          <p className="text-xs text-text-muted tracking-widest uppercase animate-pulse">Loading dashboard</p>
        </div>
      </div>
    </div>
  );
}
