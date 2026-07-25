/**
 * Push registration.
 *
 * The behaviour worth pinning is what it *declines* to do: a token must never be registered
 * against the user's wishes, on a device that cannot receive push, or after a denied
 * permission — and none of those cases may surface as an error, because they are all normal.
 */

import * as Notifications from 'expo-notifications';

import { registerForPush } from '../usePushRegistration';

/**
 * Backed by a getter: assigning to the imported namespace does not reach the module binding
 * under Babel's interop, so a plain `{ isDevice: true }` mock cannot be flipped per test.
 */
const mockDeviceState = { isDevice: true };
jest.mock('expo-device', () => ({
  get isDevice() {
    return mockDeviceState.isDevice;
  },
}));
jest.mock('expo-notifications', () => ({
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(),
}));

const mockedNotifications = Notifications as jest.Mocked<typeof Notifications>;

describe('registerForPush', () => {
  let register: jest.Mock;

  beforeEach(() => {
    register = jest.fn().mockResolvedValue(undefined);
    mockDeviceState.isDevice = true;
    mockedNotifications.getPermissionsAsync.mockResolvedValue({
      granted: true,
      canAskAgain: true,
    } as never);
    mockedNotifications.getExpoPushTokenAsync.mockResolvedValue({
      data: 'ExponentPushToken[abc]',
    } as never);
  });
  afterEach(() => jest.clearAllMocks());

  it('registers the token when permission is already granted', async () => {
    await registerForPush(register, true);
    expect(register).toHaveBeenCalledWith('ExponentPushToken[abc]', expect.any(String));
  });

  it('does nothing when the user turned notifications off in the app', async () => {
    // The in-app setting is consent for storing a token at all, not just for showing alerts.
    await registerForPush(register, false);
    expect(register).not.toHaveBeenCalled();
    expect(mockedNotifications.getPermissionsAsync).not.toHaveBeenCalled();
  });

  it('does not prompt on a simulator', async () => {
    mockDeviceState.isDevice = false;
    await registerForPush(register, true);
    expect(mockedNotifications.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(register).not.toHaveBeenCalled();
  });

  it('asks once when permission has not been decided', async () => {
    mockedNotifications.getPermissionsAsync.mockResolvedValue({
      granted: false,
      canAskAgain: true,
    } as never);
    mockedNotifications.requestPermissionsAsync.mockResolvedValue({ granted: true } as never);

    await registerForPush(register, true);

    expect(mockedNotifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalled();
  });

  it('does not re-prompt once the user has permanently declined', async () => {
    mockedNotifications.getPermissionsAsync.mockResolvedValue({
      granted: false,
      canAskAgain: false,
    } as never);

    await registerForPush(register, true);

    expect(mockedNotifications.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(register).not.toHaveBeenCalled();
  });

  it('stays silent when the permission is refused', async () => {
    mockedNotifications.getPermissionsAsync.mockResolvedValue({
      granted: false,
      canAskAgain: true,
    } as never);
    mockedNotifications.requestPermissionsAsync.mockResolvedValue({ granted: false } as never);

    await expect(registerForPush(register, true)).resolves.toBeUndefined();
    expect(register).not.toHaveBeenCalled();
  });

  it('swallows a failed registration', async () => {
    // Offline at launch is ordinary; the in-app inbox still works without a push token.
    register.mockRejectedValue(new Error('network'));
    await expect(registerForPush(register, true)).resolves.toBeUndefined();
  });

  it('swallows a failed token fetch', async () => {
    mockedNotifications.getExpoPushTokenAsync.mockRejectedValue(new Error('no project id'));
    await expect(registerForPush(register, true)).resolves.toBeUndefined();
    expect(register).not.toHaveBeenCalled();
  });
});
