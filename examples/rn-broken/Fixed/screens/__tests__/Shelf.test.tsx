import React from 'react';
import { Dimensions } from 'react-native';
import { render } from '@testing-library/react-native';
import { Shelf } from '../Shelf';

// Test files never run on a device: this module-scope read is not a layout bug.
const { width } = Dimensions.get('window');

test('renders at the mocked width', () => {
  const tree = render(<Shelf width={width} />);
  expect(tree).toBeTruthy();
});
