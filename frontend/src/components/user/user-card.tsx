import type { UserInfo } from "@/types"

type UserCardProps = {
  user: UserInfo
  onClick: (user: UserInfo) => void
}

export function UserCard({ user, onClick }: UserCardProps) {
  return (
    <button
      type="button"
      onClick={() => onClick(user)}
      className="group relative flex flex-col items-center gap-4 rounded-2xl border-2 border-border
                 bg-card p-8 shadow-sm transition-all duration-300
                 hover:border-primary/50 hover:shadow-lg hover:shadow-primary/10
                 hover:scale-[1.03] active:scale-[0.98]
                 cursor-pointer w-48"
    >
      <div className="flex size-24 items-center justify-center rounded-full bg-muted text-5xl
                      transition-transform duration-300 group-hover:scale-110">
        {user.gender === "female" ? "👩" : "👨"}
      </div>
      <span className="text-lg font-semibold text-foreground">{user.name}</span>
    </button>
  )
}