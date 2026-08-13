from pathlib import Path
import subprocess


def test_purchase_ui_exposes_a_single_api_submission_refresh_action():
    html = Path("external_systems/ui/index.html").read_text(encoding="utf-8")
    script = Path("external_systems/ui/app.js").read_text(encoding="utf-8")

    assert 'id="refresh-submissions-button"' in html
    assert "async function refreshSubmissions()" in script
    assert "request('/api/submissions')" in script
    assert "refresh-submissions-button" in script


def test_purchase_ui_exposes_purchase_follow_up_form_and_refresh():
    html = Path("external_systems/ui/index.html").read_text(encoding="utf-8")
    script = Path("external_systems/ui/app.js").read_text(encoding="utf-8")

    assert 'id="purchase-follow-up-form"' in html
    assert 'id="follow-up-mes-apply-no"' not in html
    assert 'id="follow-up-items"' in html
    assert 'data-field="material_code"' in html
    assert 'data-field="quantity"' in html
    assert 'data-field="unit"' in html
    assert 'data-field="suggested_supplier"' in html
    assert 'data-field="required_date"' in html
    assert 'id="add-follow-up-item"' in html
    assert 'id="purchase-follow-up-list"' in html
    assert "async function createPurchaseFollowUp(event)" in script
    assert "request('/api/purchase-follow-ups'" in script


def test_purchase_ui_test_data_button_fills_two_visible_detail_rows():
    html = Path("external_systems/ui/index.html").read_text(encoding="utf-8")
    assert 'id="fill-follow-up-test-data"' in html

    javascript = r"""
const fs = require('fs')
const vm = require('vm')

    function makeRow() {
  const fields = Object.fromEntries([
    'material_code', 'quantity', 'unit', 'suggested_supplier', 'required_date', 'remark'
      ].map((name) => [name, {
        value: '',
        dispatched: [],
        dispatchEvent(event) { this.dispatched.push(event.type) },
      }]))
  return {
    fields,
    querySelector(selector) {
      return fields[selector.match(/data-field="([^"]+)"/)[1]]
    },
    querySelectorAll() { return Object.values(fields) },
    cloneNode() { return makeRow() },
  }
}

const rows = [makeRow()]
const elements = {
  'follow-up-title': { value: '' },
  'follow-up-remark': { value: '' },
  'follow-up-items': {
    querySelector: () => rows[0],
    querySelectorAll: () => rows,
    appendChild: (row) => rows.push(row),
  },
}
const context = {
  console,
  crypto: { randomUUID: () => 'test-id' },
  document: { getElementById: (id) => elements[id] },
  setTimeout: () => {},
  Event: class { constructor(type) { this.type = type } },
  __COMMANDCENTER_DISABLE_AUTO_INIT__: true,
}
context.globalThis = context
vm.createContext(context)
vm.runInContext(fs.readFileSync('external_systems/ui/app.js', 'utf8'), context)
vm.runInContext('fillFollowUpTestData()', context)

const result = {
  title: elements['follow-up-title'].value,
  remark: elements['follow-up-remark'].value,
  rows: rows.map((row) => Object.fromEntries(Object.entries(row.fields).map(([key, input]) => [key, input.value]))),
  events: rows.map((row) => Object.fromEntries(Object.entries(row.fields).map(([key, input]) => [key, input.dispatched]))),
}
process.stdout.write(JSON.stringify(result))
"""
    completed = subprocess.run(
        ["node", "-e", javascript],
        cwd=Path.cwd(),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == (
        '{"title":"采购申请跟进","remark":"联合录制测试",'
        '"rows":[{"material_code":"LCF4607A","quantity":"600","unit":"KG",'
        '"suggested_supplier":"陶氏有机硅(张家港)","required_date":"2026-04-21","remark":""},'
        '{"material_code":"LCF4607B","quantity":"600","unit":"KG",'
        '"suggested_supplier":"陶氏有机硅(张家港)","required_date":"2026-04-21","remark":""}],'
        '"events":[{"material_code":["input","change"],"quantity":["input","change"],'
        '"unit":["input","change"],"suggested_supplier":["input","change"],'
        '"required_date":["input","change"],"remark":["input","change"]},'
        '{"material_code":["input","change"],"quantity":["input","change"],'
        '"unit":["input","change"],"suggested_supplier":["input","change"],'
        '"required_date":["input","change"],"remark":["input","change"]}]}'
    )
