import { ApiError } from '@study-league/api-client';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SignIn } from '../SignIn';

const signIn = vi.fn();

vi.mock('@/features/auth/AuthProvider', () => ({
  useAuth: () => ({ signIn }),
}));

function fillAndSubmit(email: string, password: string) {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('SignIn', () => {
  it('submits the trimmed email and password', async () => {
    signIn.mockResolvedValueOnce(undefined);
    render(<SignIn />);

    fillAndSubmit('  student@example.com  ', 'password123');

    await waitFor(() =>
      expect(signIn).toHaveBeenCalledWith('student@example.com', 'password123'),
    );
  });

  it('shows a friendly message on invalid credentials', async () => {
    signIn.mockRejectedValueOnce(new ApiError(401, 'invalid_credentials', 'nope'));
    render(<SignIn />);

    fillAndSubmit('student@example.com', 'wrong');

    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  });
});
