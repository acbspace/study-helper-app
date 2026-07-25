/**
 * The report control — the only entrance to a moderation pipeline that was complete
 * server-side but had no way to receive anything.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import { ApiError } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { ReportButton } from '../ReportButton';

const mockReport = jest.fn();
const mockReset = jest.fn();
const mockMutation = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useReportContent: () => mockMutation(),
}));

function renderButton(props: Partial<React.ComponentProps<typeof ReportButton>> = {}) {
  return render(
    <ThemeProvider>
      <ReportButton subjectType="post" subjectId="p1" subjectLabel="this post" {...props} />
    </ThemeProvider>,
  );
}

describe('ReportButton', () => {
  beforeEach(() => {
    mockMutation.mockReturnValue({
      mutate: mockReport,
      reset: mockReset,
      isPending: false,
      isError: false,
      error: null,
    });
  });
  afterEach(() => jest.clearAllMocks());

  it('opens the sheet', () => {
    renderButton();
    expect(screen.queryByTestId('report-sheet')).toBeNull();
    fireEvent.press(screen.getByTestId('report-open'));
    expect(screen.getByTestId('report-sheet')).toBeTruthy();
  });

  it('will not send an empty reason', () => {
    renderButton();
    fireEvent.press(screen.getByTestId('report-open'));
    fireEvent.press(screen.getByTestId('report-submit'));
    // Below the server's 3-character minimum, so the button is disabled and nothing is sent.
    expect(mockReport).not.toHaveBeenCalled();
  });

  it('sends the report with its subject', () => {
    renderButton({ subjectType: 'user', subjectId: 'u9', subjectLabel: 'Alice' });
    fireEvent.press(screen.getByTestId('report-open'));
    fireEvent.changeText(screen.getByTestId('report-reason'), 'Harassing me in comments');
    fireEvent.press(screen.getByTestId('report-submit'));

    expect(mockReport).toHaveBeenCalledWith(
      { subject_type: 'user', subject_id: 'u9', reason: 'Harassing me in comments' },
      expect.anything(),
    );
  });

  it('trims the reason before sending', () => {
    renderButton();
    fireEvent.press(screen.getByTestId('report-open'));
    fireEvent.changeText(screen.getByTestId('report-reason'), '   spam   ');
    fireEvent.press(screen.getByTestId('report-submit'));
    expect(mockReport).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'spam' }),
      expect.anything(),
    );
  });

  it('confirms once the report is filed', () => {
    mockReport.mockImplementation((_input, options) => options.onSuccess());
    renderButton();
    fireEvent.press(screen.getByTestId('report-open'));
    fireEvent.changeText(screen.getByTestId('report-reason'), 'Spam links');
    fireEvent.press(screen.getByTestId('report-submit'));
    expect(screen.getByTestId('report-done')).toBeTruthy();
  });

  it('explains a duplicate report in the user’s terms', () => {
    mockMutation.mockReturnValue({
      mutate: mockReport,
      reset: mockReset,
      isPending: false,
      isError: true,
      error: new ApiError(409, 'report_exists', 'Report exists.'),
    });
    renderButton();
    fireEvent.press(screen.getByTestId('report-open'));
    expect(screen.getByText(/already reported this/)).toBeTruthy();
  });

  it('names the subject so the user knows what they are reporting', () => {
    renderButton({ subjectType: 'group', subjectId: 'g1', subjectLabel: 'Morning Focus' });
    fireEvent.press(screen.getByTestId('report-open'));
    expect(screen.getByText('Report Morning Focus')).toBeTruthy();
  });
});
