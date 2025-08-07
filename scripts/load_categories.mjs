import fs from 'fs';

export function loadCategories() {
  const data = fs.readFileSync('./folder_map.json', 'utf-8');
  const folderMap = JSON.parse(data);
  return Object.keys(folderMap).map((name) => ({
    label: name.charAt(0).toUpperCase() + name.slice(1),
    value: name,
  }));
}

// When executed directly, output the derived categories
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(loadCategories());
}
