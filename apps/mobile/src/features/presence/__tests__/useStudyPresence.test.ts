/**
 * Presence heartbeats follow the timer: studying while active, break while paused, and one
 * "offline" when a session that was broadcasting ends. Auth and the timer store are mocked
 * so the hook is tested in isolation.
 */

import { renderHook } from '@testing-library/react-native';

import { useStudyPresence } from '../useStudyPresence';

const mockSendHeartbeat = jest.fn().mockResolvedValue(undefined);
const mockGoOffline = jest.fn().mockResolvedValue(undefined);
let mockTimerSlice: { state: { status: string }; subjectId: string | null } = {
  state: { status: 'idle' },
  subjectId: null,
};

jest.mock('@/features/auth/AuthProvider', () => ({
  useAuth: () => ({
    client: { sendHeartbeat: mockSendHeartbeat, goOffline: mockGoOffline },
    status: 'authenticated',
  }),
}));

jest.mock('@/features/timer/timerStore', () => ({
  useTimerStore: (selector: (slice: unknown) => unknown) => selector(mockTimerSlice),
}));

describe('useStudyPresence', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockTimerSlice = { state: { status: 'idle' }, subjectId: null };
  });

  it('heartbeats "studying" while the timer is active', () => {
    mockTimerSlice = { state: { status: 'active' }, subjectId: 's1' };
    const { unmount } = renderHook(() => useStudyPresence());
    expect(mockSendHeartbeat).toHaveBeenCalledWith({ state: 'studying', subject_id: 's1' });
    unmount();
  });

  it('heartbeats "break" while paused', () => {
    mockTimerSlice = { state: { status: 'paused' }, subjectId: 's1' };
    const { unmount } = renderHook(() => useStudyPresence());
    expect(mockSendHeartbeat).toHaveBeenCalledWith({ state: 'break', subject_id: 's1' });
    unmount();
  });

  it('goes offline once after a broadcasting session ends', () => {
    mockTimerSlice = { state: { status: 'active' }, subjectId: 's1' };
    const { rerender, unmount } = renderHook(() => useStudyPresence());
    expect(mockGoOffline).not.toHaveBeenCalled();

    mockTimerSlice = { state: { status: 'idle' }, subjectId: null };
    rerender({});
    expect(mockGoOffline).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('does nothing while idle and never active', () => {
    const { unmount } = renderHook(() => useStudyPresence());
    expect(mockSendHeartbeat).not.toHaveBeenCalled();
    expect(mockGoOffline).not.toHaveBeenCalled();
    unmount();
  });
});
