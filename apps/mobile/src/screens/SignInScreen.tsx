/**
 * Sign in / sign up.
 *
 * React Hook Form + Zod so validation rules live in one schema and match the server's,
 * rather than being re-derived per field.
 */

import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { zodResolver } from '@hookform/resolvers/zod';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';
import { ApiError } from '@study-league/api-client';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Text } from '@/components/Text';
import { resolveDeviceTimezone, useAuth } from '@/features/auth/AuthProvider';
import { useTheme } from '@/theme/ThemeProvider';

const signInSchema = z.object({
  email: z.string().min(1, 'Enter your email').email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password'),
});

const signUpSchema = signInSchema.extend({
  // Mirrors the server's rules so the user is never rejected after a round trip for
  // something the app could have told them immediately.
  password: z.string().min(8, 'Use at least 8 characters'),
  username: z
    .string()
    .min(3, 'At least 3 characters')
    .max(30, 'At most 30 characters')
    .regex(/^[A-Za-z0-9_.]+$/, 'Letters, numbers, underscore and dot only'),
});

// Both modes share one form instance, so the wider sign-up shape types it; the sign-in
// resolver simply validates a subset of the fields.
type SignUpValues = z.infer<typeof signUpSchema>;

export function SignInScreen(): React.ReactElement {
  const { theme } = useTheme();
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'sign-in' | 'sign-up'>('sign-in');
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isSignUp = mode === 'sign-up';

  const form = useForm<SignUpValues>({
    resolver: zodResolver(
      isSignUp ? signUpSchema : (signInSchema as unknown as typeof signUpSchema),
    ),
    defaultValues: { email: '', password: '', username: '' },
  });

  const onSubmit = async (values: SignUpValues) => {
    setSubmitting(true);
    setFormError(null);
    try {
      if (isSignUp) {
        await signUp({
          email: values.email,
          password: values.password,
          username: values.username,
          timezone: resolveDeviceTimezone(),
        });
      } else {
        await signIn(values.email, values.password);
      }
    } catch (error) {
      setFormError(toMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} testID="sign-in-screen">
        <View style={styles.header}>
          <Text variant="display">Study League</Text>
          <Text variant="body" color="secondary">
            Consistency beats cramming. Track focused study, plan your day, and compete fairly.
          </Text>
        </View>

        <Card>
          <Field
            control={form.control}
            name="email"
            label="Email"
            placeholder="you@example.com"
            keyboardType="email-address"
            autoComplete="email"
            testID="input-email"
            error={form.formState.errors.email?.message}
          />

          {isSignUp ? (
            <Field
              control={form.control}
              name="username"
              label="Username"
              placeholder="studyhero"
              autoComplete="username"
              testID="input-username"
              error={form.formState.errors.username?.message}
            />
          ) : null}

          <Field
            control={form.control}
            name="password"
            label="Password"
            placeholder={isSignUp ? 'At least 8 characters' : 'Your password'}
            secureTextEntry
            autoComplete={isSignUp ? 'new-password' : 'current-password'}
            testID="input-password"
            error={form.formState.errors.password?.message}
          />

          {formError ? (
            <Text variant="caption" color="danger" accessibilityRole="alert" testID="form-error">
              {formError}
            </Text>
          ) : null}

          <Button
            testID="submit-button"
            label={isSignUp ? 'Create account' : 'Sign in'}
            size="large"
            loading={submitting}
            onPress={() => void form.handleSubmit(onSubmit)()}
          />

          <Button
            testID="toggle-mode"
            label={isSignUp ? 'I already have an account' : 'Create a new account'}
            variant="ghost"
            onPress={() => {
              setMode(isSignUp ? 'sign-in' : 'sign-up');
              setFormError(null);
              form.clearErrors();
            }}
          />
        </Card>

        <Text variant="caption" color="secondary" align="center">
          Signing in on a development build? Use the seeded account from the README.
        </Text>

        <View style={{ height: spacing.xl, backgroundColor: theme.background }} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

/** A labelled text input wired to react-hook-form, with accessible error reporting. */
function Field({
  control,
  name,
  label,
  error,
  testID,
  ...inputProps
}: {
  control: ReturnType<typeof useForm<SignUpValues>>['control'];
  name: keyof SignUpValues;
  label: string;
  error?: string;
  testID?: string;
} & React.ComponentProps<typeof TextInput>): React.ReactElement {
  const { theme, fontSize } = useTheme();

  return (
    <View style={styles.field}>
      <Text variant="label">{label}</Text>
      <Controller
        control={control}
        name={name}
        render={({ field: { onChange, onBlur, value } }) => (
          <TextInput
            testID={testID}
            value={value}
            onChangeText={onChange}
            onBlur={onBlur}
            autoCapitalize="none"
            autoCorrect={false}
            accessibilityLabel={label}
            accessibilityHint={error}
            placeholderTextColor={theme.textSecondary}
            style={{
              minHeight: minTouchTarget,
              borderRadius: radius.md,
              borderWidth: 1,
              borderColor: error ? theme.danger : theme.border,
              backgroundColor: theme.surfaceMuted,
              color: theme.textPrimary,
              paddingHorizontal: spacing.md,
              fontSize: fontSize('body'),
            }}
            {...inputProps}
          />
        )}
      />
      {error ? (
        <Text variant="caption" color="danger" accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

function toMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'network_error') {
      return 'Could not reach the server. Check your connection and try again.';
    }
    return error.message;
  }
  return 'Something went wrong. Please try again.';
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: spacing.lg, gap: spacing.xl, justifyContent: 'center', flexGrow: 1 },
  header: { gap: spacing.sm },
  field: { gap: spacing.xs },
});
