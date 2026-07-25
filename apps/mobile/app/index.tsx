import { Redirect } from 'expo-router';

/** The root route defers to the auth gate in `_layout.tsx`. */
export default function Index() {
  return <Redirect href="/(tabs)/today" />;
}
