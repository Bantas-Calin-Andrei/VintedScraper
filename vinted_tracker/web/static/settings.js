function addBrand(button) {
  const key = button.dataset.group;
  const id = button.dataset.id;
  const title = button.dataset.title;
  const box = document.getElementById('brands-' + key);
  if (!box) return;
  const already = [...box.querySelectorAll('input[type=hidden]')].some((i) => i.value.split('|')[0] === id);
  if (!already) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'brand_' + key;
    input.value = id + '|' + title;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'x';
    remove.title = 'Remove';
    remove.textContent = '✕';
    remove.onclick = () => chip.remove();
    chip.append(input, document.createTextNode(title + ' '), remove);
    box.appendChild(chip);
  }
  button.closest('.results').innerHTML = '';
}

function addGroup() {
  const key = 'n' + Date.now();
  const html = document.getElementById('group-template').innerHTML.replaceAll('__KEY__', key);
  const groups = document.getElementById('groups');
  groups.insertAdjacentHTML('beforeend', html);
  htmx.process(groups.lastElementChild);
  groups.lastElementChild.querySelector('input[name^="group_name_"]').focus();
}
