<template>
  <section class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">AI Config Draft</p>
        <h2>AI 生成表单配置</h2>
      </div>
    </div>

    <div class="two-column">
      <el-card class="panel" shadow="never">
        <template #header>接口说明</template>
        <div class="demo-examples">
          <span>快速演示：</span>
          <el-button type="primary" plain @click="loadDemo('workflow')">
            流程类采购系统
          </el-button>
          <el-button type="success" plain @click="loadDemo('custom_url')">
            独立 URL 类办公用品系统
          </el-button>
        </div>
        <el-form label-position="top">
          <el-form-item label="表单名称" required>
            <el-input v-model="formName" placeholder="例如：办公用品申请" />
          </el-form-item>
          <el-form-item label="接口说明 / 字段说明" required>
            <el-input
              v-model="description"
              type="textarea"
              :rows="16"
              placeholder="粘贴客户提供的接口 URL、入参、formValues 示例等"
            />
          </el-form-item>
          <el-button type="primary" :loading="generating" @click="generate">生成配置草稿</el-button>
        </el-form>
      </el-card>

      <div class="stack">
        <el-card class="panel" shadow="never">
          <template #header>配置摘要</template>
          <el-empty v-if="!draftConfig" description="暂无配置草稿" />
          <div v-else class="summary">
            <div class="summary-actions">
              <el-alert
                title="保存后对应业务系统会自动接入，并出现在任务中心。"
                type="info"
                show-icon
                :closable="false"
              />
              <el-button type="success" :loading="saving" @click="saveDraft">保存为正式表单</el-button>
            </div>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="表单名称">{{ draftConfig.form_name }}</el-descriptions-item>
              <el-descriptions-item label="表单编码">{{ draftConfig.form_code }}</el-descriptions-item>
              <el-descriptions-item label="接口类型">
                <el-tag>{{ endpointTypeText(draftConfig.endpoint_type) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="提交方式">
                <el-tag :type="draftConfig.endpoint.submit_mode === 'http' ? 'danger' : 'success'">
                  {{ submitModeText(draftConfig.endpoint.submit_mode) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="字段数量">{{ flatFields.length }}</el-descriptions-item>
              <el-descriptions-item label="接口地址" :span="2">
                {{ draftConfig.endpoint.url }}
              </el-descriptions-item>
              <el-descriptions-item v-if="draftConfig.endpoint.fdTemplateId" label="流程模板 ID" :span="2">
                {{ draftConfig.endpoint.fdTemplateId }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>

        <el-card class="panel" shadow="never">
          <template #header>识别出的字段</template>
          <el-empty v-if="!draftConfig" description="暂无字段" />
          <el-table v-else :data="flatFields" border>
            <el-table-column prop="label" label="字段名称" min-width="140" />
            <el-table-column prop="key" label="字段 key" min-width="150" />
            <el-table-column prop="type" label="类型" width="100" />
            <el-table-column label="必填" width="80">
              <template #default="{ row }">
                <el-tag :type="row.required ? 'danger' : 'info'">
                  {{ row.required ? '是' : '否' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="parent" label="所属明细" min-width="120" />
          </el-table>
        </el-card>

        <el-card class="panel" shadow="never">
          <template #header>风险提示</template>
          <el-empty v-if="warnings.length === 0" description="暂无提示" />
          <el-alert
            v-for="warning in warnings"
            v-else
            :key="warning"
            :title="warning"
            type="warning"
            show-icon
            :closable="false"
            class="warning-item"
          />
        </el-card>

        <el-collapse v-if="draftConfig">
          <el-collapse-item title="高级配置 JSON（给技术人员或系统保存使用）" name="json">
            <JsonPreview :value="draftConfig" />
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateFormConfig } from '../api/aiConfig'
import { createForm } from '../api/forms'
import type { EndpointType, FormField, FormTemplate, SubmitMode } from '../api/types'
import JsonPreview from '../components/JsonPreview.vue'

const formName = ref('')
const description = ref('')
const draftConfig = ref<FormTemplate | null>(null)
const warnings = ref<string[]>([])
const generating = ref(false)
const saving = ref(false)

interface DisplayField {
  label: string
  key: string
  type: string
  required: boolean
  parent: string
}

const flatFields = computed<DisplayField[]>(() => {
  if (!draftConfig.value) return []
  return draftConfig.value.fields.flatMap((field) => flattenField(field))
})

function loadDemo(type: EndpointType) {
  draftConfig.value = null
  warnings.value = []
  if (type === 'workflow') {
    formName.value = '采购申请'
    description.value = 'POST http://127.0.0.1:8101/api/workflows/start。流程类接口，请求格式为 form-data。所有流程共用这个启动接口，通过 fdTemplateId 区分单据，本表单 fdTemplateId 为 purchase_request_001。参数包含 docSubject、fdTemplateId、formValues、docCreator、docStatus。formValues 示例 {"fd_item_name":"包装箱","fd_quantity":20,"fd_reason":"仓库库存不足"}。字段说明：fd_item_name 为采购物品，fd_quantity 为数量，fd_reason 为采购原因，均为必填。请生成 endpoint_type 为 workflow、submit_mode 为 http 的配置。'
    return
  }
  formName.value = '办公用品申请'
  description.value = 'POST http://127.0.0.1:8102/api/forms/submit。独立 URL 类接口，请求格式为 form-data。入参只有 docOperator 和 formValues。docOperator 示例 {"Id":"u001"}。formValues 示例 {"itemName":"签字笔","quantity":10,"usage":"会议使用","applicant":"王五"}。字段说明：itemName 为申请物品，quantity 为数量，usage 为用途，applicant 为申请人，均为必填。请生成 endpoint_type 为 custom_url、submit_mode 为 http 的配置。'
}

async function generate() {
  generating.value = true
  try {
    const response = await generateFormConfig({
      form_name: formName.value,
      description: description.value,
    })
    draftConfig.value = response.draft_config
    warnings.value = response.warnings
    ElMessage.success('配置草稿已生成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成失败')
  } finally {
    generating.value = false
  }
}

async function saveDraft() {
  if (!draftConfig.value) return
  saving.value = true
  try {
    await createForm(draftConfig.value)
    ElMessage.success('已保存为正式表单')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

function flattenField(field: FormField, parent = ''): DisplayField[] {
  const current = {
    label: field.label,
    key: field.key,
    type: field.type,
    required: field.required,
    parent,
  }
  if (field.type !== 'list') {
    return [current]
  }
  return [
    current,
    ...field.item_fields.flatMap((itemField) => flattenField(itemField, field.label)),
  ]
}

function endpointTypeText(type: EndpointType) {
  return type === 'workflow' ? '流程类接口' : '自定义 URL 接口'
}

function submitModeText(mode: SubmitMode) {
  return mode === 'http' ? '真实接口提交' : '模拟提交'
}
</script>

<style scoped>
.summary-actions {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
}

.demo-examples {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 18px;
}

.demo-examples span {
  color: #606266;
  font-size: 14px;
}

.summary-actions .el-button {
  justify-self: start;
}
</style>
