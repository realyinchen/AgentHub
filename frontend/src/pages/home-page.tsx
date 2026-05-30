import type { UserInfo } from "@/types"
import { UserCard } from "@/components/user/user-card"

const USERS: UserInfo[] = [
  { id: "user-male", name: "Jack", avatar: "", gender: "male" },
  { id: "user-female", name: "Rose", avatar: "", gender: "female" },
]

type HomePageProps = {
  onSelectUser: (user: UserInfo) => void
}

export function HomePage({ onSelectUser }: HomePageProps) {
  return (
    <div className="flex min-h-screen items-center justify-center gap-8 bg-background">
      {USERS.map((user) => (
        <UserCard key={user.id} user={user} onClick={() => onSelectUser(user)} />
      ))}
    </div>
  )
}