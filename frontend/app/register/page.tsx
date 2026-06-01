'use client'

import { useState, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuthStore } from '@/lib/stores/authStore'
import { authApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { USER_ROLES, type UserRole, type InviteValidateResponse } from '@/types'
import { Users } from 'lucide-react'

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  )
}

function RegisterForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { register, isLoading, error, clearError } = useAuthStore()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [role, setRole] = useState<UserRole>('developer')
  const [validationError, setValidationError] = useState('')
  const [adminExists, setAdminExists] = useState<boolean | null>(null)

  // Invite token state
  const inviteToken = searchParams.get('invite') || ''
  const [invite, setInvite] = useState<InviteValidateResponse | null>(null)
  const [inviteError, setInviteError] = useState('')

  // Validate invite token on mount if present
  useEffect(() => {
    if (!inviteToken) return
    authApi.validateInvite(inviteToken)
      .then((res) => {
        const data: InviteValidateResponse = res.data
        if (!data.valid) {
          setInviteError('This invite link is invalid or has already been used.')
        } else {
          setInvite(data)
          if (data.role) setRole(data.role)
          if (data.email) setEmail(data.email)
        }
      })
      .catch(() => setInviteError('Could not validate invite link.'))
  }, [inviteToken])

  // Check if an admin already exists to conditionally show/hide the Admin role option
  useEffect(() => {
    if (invite) return  // invite flow bypasses admin check
    authApi.checkAdminExists()
      .then(res => {
        const exists = res.data.admin_exists as boolean
        setAdminExists(exists)
        if (exists) setRole(prev => prev === 'admin' ? 'developer' : prev)
      })
      .catch(() => setAdminExists(false))
  }, [invite])

  const availableRoles = invite
    ? USER_ROLES.filter(r => r.value === invite.role)
    : adminExists
      ? USER_ROLES.filter(r => r.value !== 'admin')
      : USER_ROLES

  const selectedRoleInfo = availableRoles.find(r => r.value === role)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    setValidationError('')

    if (password !== confirmPassword) {
      setValidationError('Passwords do not match')
      return
    }
    if (password.length < 8) {
      setValidationError('Password must be at least 8 characters')
      return
    }

    try {
      await register({
        email,
        password,
        full_name: fullName,
        role,
        ...(inviteToken ? { invite_token: inviteToken } : {}),
      })
      router.push('/dashboard')
    } catch {
      // Error handled in store
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12 sm:px-6 lg:px-8">
      <Card className="w-full max-w-lg">
        <CardHeader className="space-y-1">
          <CardTitle className="text-3xl font-bold text-center">Synkro</CardTitle>
          <CardDescription className="text-center">
            {invite ? `Join ${invite.team_name}` : 'Create your account to get started'}
          </CardDescription>
        </CardHeader>

        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {/* Invite banner */}
            {invite && (
              <div className="flex items-start gap-3 rounded-md bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 p-3 text-sm text-indigo-800 dark:text-indigo-200">
                <Users className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium">You have been invited to join <span className="font-semibold">{invite.team_name}</span></p>
                  <p className="text-xs mt-0.5 text-indigo-600 dark:text-indigo-400">Your role will be set to <span className="font-medium capitalize">{invite.role?.replace(/_/g, ' ')}</span></p>
                </div>
              </div>
            )}

            {inviteError && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{inviteError}</div>
            )}

            {(error || validationError) && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">
                {validationError || error}
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="fullName">Full Name</Label>
              <Input
                id="fullName"
                type="text"
                placeholder="John Doe"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isLoading || (!!invite && !!invite.email)}
              />
              {invite && invite.email && (
                <p className="text-xs text-muted-foreground">Email locked to the invited address</p>
              )}
            </div>

            {/* Role Selection */}
            <div className="space-y-2">
              <Label htmlFor="role">Role / Position</Label>
              <select
                id="role"
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                disabled={isLoading || !!invite}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                required
              >
                {availableRoles.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
              {selectedRoleInfo && (
                <p className="text-xs text-muted-foreground">{selectedRoleInfo.description}</p>
              )}
              {!invite && adminExists && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  An admin account already exists. You can register with any other role.
                </p>
              )}
              {invite && (
                <p className="text-xs text-indigo-600 dark:text-indigo-400">
                  Role assigned by the team admin.
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
                minLength={8}
              />
              <p className="text-xs text-gray-500">At least 8 characters</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm Password</Label>
              <Input
                id="confirmPassword"
                type="password"
                placeholder="••••••••"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            {!invite && (
              <div className="rounded-md bg-blue-50 p-3 text-xs text-blue-800">
                <p className="font-medium mb-1">Role Hierarchy in Synkro:</p>
                <ul className="space-y-0.5">
                  <li><span className="font-medium">Admin</span> — Upload meetings, manage users, full access</li>
                  <li><span className="font-medium">Project Manager / Team Lead</span> — Assign tasks, view meetings</li>
                  <li><span className="font-medium">Senior Dev / Developer / Intern</span> — Email integration, task management</li>
                </ul>
              </div>
            )}
          </CardContent>

          <CardFooter className="flex flex-col space-y-4">
            <Button
              type="submit"
              className="w-full"
              disabled={isLoading || !!inviteError}
            >
              {isLoading ? 'Creating account...' : invite ? `Join ${invite.team_name}` : 'Create Account'}
            </Button>

            <p className="text-center text-sm text-gray-600">
              Already have an account?{' '}
              <Link href="/login" className="font-medium text-primary hover:underline">
                Sign in
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
