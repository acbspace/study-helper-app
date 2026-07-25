module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      // Reanimated v4 ships its Babel plugin via react-native-worklets; it must stay last.
      'react-native-worklets/plugin',
    ],
  };
};
