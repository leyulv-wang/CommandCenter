import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createRecording,
  listRecordings,
  startRecording,
  stopRecording,
} from '../../api/commandCenter'
import DemonstrationWorkbenchPage from '../DemonstrationWorkbenchPage.vue'

vi.mock('../../api/commandCenter', () => ({
  createRecording: vi.fn(),
  listRecordings: vi.fn(),
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
}))

const createdRecording = {
  recording_id: 'recording-1',
  status: 'created' as const,
  objective: '创建采购申请',
  source_system: 'connected_system',
  source_task_id: 'purchase-demonstration',
}

async function finishDemonstration(result: Record<string, unknown>) {
  vi.mocked(createRecording).mockResolvedValue(createdRecording)
  vi.mocked(startRecording).mockResolvedValue({
    ...createdRecording,
    status: 'recording',
  })
  vi.mocked(stopRecording).mockResolvedValue(result as typeof createdRecording)
  const wrapper = shallowMount(DemonstrationWorkbenchPage)

  await wrapper.findAll('el-button')[0].trigger('click')
  await flushPromises()
  await wrapper.findAll('el-button')[1].trigger('click')
  await flushPromises()

  return wrapper
}

describe('DemonstrationWorkbenchPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(listRecordings).mockResolvedValue([])
  })

  it('presents the employee demonstration sequence and explicit controls', () => {
    const wrapper = shallowMount(DemonstrationWorkbenchPage)

    expect(wrapper.text()).toContain('演示工作台')
    expect(wrapper.text()).toContain('观察')
    expect(wrapper.text()).toContain('学习')
    expect(wrapper.text()).toContain('测试')
    expect(wrapper.text()).toContain('发布')
    expect(wrapper.text()).toContain('开始演示')
    expect(wrapper.text()).toContain('结束演示')
    expect(wrapper.text()).toContain('在采购系统填写并提交一条采购申请')
    expect(wrapper.text()).not.toContain('回写')
    expect(wrapper.find('input[placeholder="OFFICE-TASK-0001"]').exists()).toBe(false)
  })

  it('shows analysis rejection at the learning step with the agent reason', async () => {
    const wrapper = await finishDemonstration({
      ...createdRecording,
      status: 'needs_reteach',
      failure_stage: 'analysis',
      failure_reasons: ['未观察到创建采购申请接口'],
    })

    expect(wrapper.text()).toContain('演示内容无法生成 Skill')
    expect(wrapper.text()).toContain('未观察到创建采购申请接口')
    expect(wrapper.text()).not.toContain('自动测试没有通过')
    const learningStep = wrapper.findAll('li').find((item) => item.text().includes('学习'))
    expect(learningStep?.classes()).toContain('active')
  })

  it('uses neutral feedback for legacy rejected recordings', async () => {
    const wrapper = await finishDemonstration({
      ...createdRecording,
      status: 'needs_reteach',
    })

    expect(wrapper.text()).toContain('本次演示未能发布 Skill')
    expect(wrapper.text()).not.toContain('自动测试没有通过')
  })

  it('shows a real harmless-test rejection at the testing step', async () => {
    const wrapper = await finishDemonstration({
      ...createdRecording,
      status: 'needs_reteach',
      failure_stage: 'testing',
      failure_reasons: ['参数变化测试未通过'],
    })

    expect(wrapper.text()).toContain('自动测试没有通过')
    expect(wrapper.text()).toContain('参数变化测试未通过')
    const testingStep = wrapper.findAll('li').find((item) => item.text().includes('测试'))
    expect(testingStep?.classes()).toContain('active')
  })

  it.each([
    ['recording', '正在录制'],
    ['upload_failed', '上传失败'],
    ['analyzing', '智能体分析中'],
    ['api_candidate', 'API Skill 已生成'],
    ['verified_candidate', 'Skill 验证成功'],
    ['rejected', 'Skill 验证失败'],
  ] as const)('shows browser extension status %s as %s', async (status, label) => {
    vi.mocked(listRecordings).mockResolvedValue([
      {
        recording_id: 'extension-recording-1',
        status,
        objective: '查询采购申请',
        source_system: 'yifeng_mes',
        capture_source: 'browser_extension',
        created_at: '2026-08-04T08:00:00+00:00',
        updated_at: '2026-08-04T08:01:00+00:00',
        failure_reasons: status === 'upload_failed' ? ['证据协议校验失败'] : [],
      },
    ])

    const wrapper = shallowMount(DemonstrationWorkbenchPage)
    await flushPromises()

    expect(wrapper.text()).toContain('浏览器扩展录制结果')
    expect(wrapper.text()).toContain(label)
    expect(wrapper.text()).toContain('查询采购申请')
    if (status === 'upload_failed') {
      expect(wrapper.text()).toContain('证据协议校验失败')
    }
    if (status === 'api_candidate') {
      expect(wrapper.text()).toContain('待业务系统配置执行连接后再做实时验证')
      expect(wrapper.text()).not.toContain('浏览器 Skill')
    }
  })
})
