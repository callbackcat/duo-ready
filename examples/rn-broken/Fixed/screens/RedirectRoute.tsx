import React from 'react';
import { Redirect } from 'expo-router';

// A route that only redirects draws nothing; it needs no safe-area handling.
export default function Index() {
  return <Redirect href="/home" />;
}
