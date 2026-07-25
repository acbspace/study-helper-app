import React from 'react';

import { Stack } from 'expo-router';

export default function AuthLayout(): React.ReactElement {
  return <Stack screenOptions={{ headerShown: false }} />;
}
