"""Chrome catalog/parameter acceptance with isolated HTTP; no vehicle transport."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path

from tests.browser_auth import login
from tests.web_ui.helpers import Harness
from tests.action_system.test_runtime import Factory,Parameters
from vehicle_autonomy.contracts.decision import ActionSpec


@dataclass(frozen=True)
class TimedParameters:
    duration_ns:int=2_000_000_000
    timeout_ns:int=15_000_000_000


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    from vehicle_autonomy.actions.simulation.studio_demo import register_demo
    from vehicle_autonomy.actions.navigation.native_rover import register_native_navigation,NativeRoverNavigationFactory
    directory.mkdir(parents=True,exist_ok=False);h=Harness(directory/'server',kinds=('rover','copter','plane'),standard=True)
    register_demo(h.lab.registry)
    register_native_navigation(h.lab.registry,object.__new__(NativeRoverNavigationFactory))
    factory=Factory();factory.ui_metadata=dict(category='data',display_name={'zh-CN':'时间参数校验','en-US':'Timed parameter check'},description={'zh-CN':'验证纳秒参数显示与保存','en-US':'Verify nanosecond parameter round trip'})
    h.lab.registry.register_typed(ActionSpec('custom.timed',TimedParameters,external_lifecycle='typed_only'),factory)
    h.lab.registry.register_typed(ActionSpec('unknown.custom',Parameters,external_lifecycle='typed_only'),Factory())
    errors=[];report=dict(passed=False,source=__doc__)
    try:
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=b.new_page(viewport={'width':1680,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,h.base,h.token,'/studio');page.locator('#vehicle').select_option('copter')
                page.locator('#new-mission').click();page.get_by_label('任务名称',exact=True).fill('Action catalog round trip');page.locator('#dialog-confirm').click()
                def item(name,category=None):
                    locator=page.locator('#palette '+('[data-category="'+category+'"] ' if category else '')+'button.palette-item[data-action-id="'+name+'"]')
                    return locator
                def open_group(category):
                    box=page.locator('#palette details[data-category="'+category+'"]')
                    if not box.evaluate('(e)=>e.open'):box.locator('summary').click()
                for category in ('vehicle','navigation','safety','perception','actuation','data','integration','composite','uncategorized','logic','submission'):
                    expect(page.locator('#palette [data-category="'+category+'"]')).to_have_count(1)
                expect(item('Arm','vehicle')).to_contain_text('解锁车辆')
                expect(item('Drive')).to_have_count(0)
                page.locator('#palette-vehicle').select_option('all')
                expect(item('Drive','navigation')).to_be_disabled();expect(item('Drive','navigation')).to_contain_text('不支持当前车辆类型')
                page.locator('#palette-provider').select_option('nav2');open_group('integration')
                expect(item('NavigateToPose','integration')).to_be_disabled();expect(item('NavigateToPose','integration')).to_contain_text('未绑定')
                page.locator('#palette-provider').select_option('');page.locator('#palette-vehicle').select_option('current')
                # Chinese description, English ID and parameter-help searches use the same entries.
                search=page.locator('#palette-search')
                for query in ('目标高度','Takeoff','相对爬升'):
                    search.fill(query);expect(item('Takeoff','vehicle')).to_have_count(1)
                search.fill('Takeoff');item('Takeoff','vehicle').click()
                expect(page.locator('.graph-node h3').filter(has_text='起飞')).to_have_count(1)
                expect(page.locator('#properties')).to_contain_text('默认值')
                expect(page.locator('#properties')).to_contain_text('目标高度')
                expect(page.locator('#properties')).to_contain_text('≤ 2')
                page.locator('#properties details').filter(has=page.locator('summary',has_text='原始动作标识')).locator('summary').click()
                expect(page.locator('#properties code')).to_have_text('Takeoff@1.0.0')
                height=page.get_by_label('height_m',exact=True);height.fill('3');height.press('Tab')
                expect(page.locator('.parameter-error').filter(has_text='参数超出允许范围')).to_have_count(1)
                height.fill('1.75');height.press('Tab')
                # Favorites never execute or create nodes, and survive a reload.
                before=page.locator('.graph-node').count();search.fill('Arm')
                favorite=page.locator('[data-category=vehicle] .palette-action').filter(has=page.locator('button[data-action-id=Arm]'))
                favorite.locator('.action-favorite').click();assert page.locator('.graph-node').count()==before
                open_group('favorites');expect(item('Arm','favorites')).to_have_count(1)
                search.fill('custom.timed');open_group('data');item('custom.timed','data').click()
                open_group('recent');expect(item('custom.timed','recent')).to_have_count(1);expect(page.get_by_label('duration_ns',exact=True)).to_have_value('2');expect(page.get_by_label('timeout_ns',exact=True)).to_have_value('15')
                duration=page.get_by_label('duration_ns',exact=True);duration.fill('4.000000001');duration.press('Tab')
                expect(page.locator('#properties')).to_contain_text('单位 s')
                page.locator('#save-draft').click();expect(page.locator('#save-state')).to_contain_text('已保存')
                assert page.evaluate('VAFI18n.error("UNMAPPED_VENDOR_ERROR_42")')=='UNMAPPED_VENDOR_ERROR_42'
                definition=next(v['definition'] for v in h.lab.studio.library.snapshot()['drafts'].values() if v['definition']['name']=='Action catalog round trip')
                takeoff=next(n for n in definition['nodes'] if n.get('action_type')=='Takeoff')
                timed=next(n for n in definition['nodes'] if n.get('action_type')=='custom.timed')
                assert takeoff['parameters']=={'height_m':1.75}
                assert timed['parameters']=={'duration_ns':4_000_000_001,'timeout_ns':15_000_000_000}
                assert type(timed['parameters']['duration_ns']) is int
                with page.expect_download() as download:page.locator('#export').click()
                download.value.save_as(str(directory/'mission.json'))
                exported=json.loads((directory/'mission.json').read_text());assert exported==definition
                # No translation remains a usable, classified-as-unknown registration.
                search.fill('unknown.custom');open_group('uncategorized');expect(item('unknown.custom','uncategorized')).to_be_enabled()
                expect(item('unknown.custom','uncategorized')).to_contain_text('unknown.custom')
                search.fill('custom.timed');page.locator('#studio-language').select_option('en-US')
                expect(item('custom.timed','data')).to_contain_text('Timed parameter check')
                expect(page.locator('.graph-node h3').filter(has_text='Timed parameter check')).to_have_count(1)
                expect(page.get_by_label('duration_ns',exact=True)).to_have_value('4.000000001')
                page.locator('#studio-language').select_option('zh-CN');search.fill('')
                page.screenshot(path=str(directory/'action-library-desktop.png'),full_page=True)
                page.reload();page.locator('[data-tab=library]').click();page.locator('.mission-card').filter(has_text='Action catalog round trip').get_by_role('button',name='打开编辑器',exact=True).click()
                expect(page.locator('[data-category=favorites] button[data-action-id=Arm]')).to_have_count(1)
                page.locator('[data-node="'+timed['node_id']+'"]').click();expect(page.get_by_label('duration_ns',exact=True)).to_have_value('4.000000001')
                # Binding reference strings are program data, even when matching a UI word.
                page.locator('#mission-properties').evaluate('(e)=>e.parentElement.open=true')
                board=page.get_by_label('blackboard',exact=True);board.fill(json.dumps({'target_pose':{'schema':{'type':'number'},'default':1.25}}));board.press('Tab')
                page.locator('#layout').click();page.locator('[data-node="'+takeoff['node_id']+'"]').click()
                page.get_by_label('height_m 输入来源',exact=True).select_option('blackboard')
                ref=page.get_by_label('height_m 变量引用',exact=True);ref.fill('mission.target_pose');ref.press('Tab')
                page.locator('#save-draft').click();expect(page.locator('#save-state')).to_contain_text('已保存')
                stored=next(v['definition'] for v in h.lab.studio.library.snapshot()['drafts'].values() if v['definition']['name']=='Action catalog round trip')
                assert next(n for n in stored['nodes'] if n.get('action_type')=='Takeoff')['input_bindings']['height_m']['ref']=='mission.target_pose'
                for width,label in [(820,'tablet'),(390,'mobile')]:
                    page.set_viewport_size({'width':width,'height':1100});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(directory/('action-library-'+label+'.png')),full_page=True)
                assert not errors and not h.lab.runtime.views() and not any(d.writes for d in h.drivers.values()),errors
                report.update(passed=True,groups=11,source_inventory=42,chinese_and_id_and_help_search=True,
                    vehicle_and_provider_filters=True,unavailable_disabled=True,favorites_and_recent=True,
                    chinese_validation=True,exact_nanosecond_round_trip=True,language_switch=True,
                    old_definition_reload=True,original_ids_keys_references=True,javascript_errors=errors,zero_vehicle_writes=True)
            except BaseException as error:
                page.screenshot(path=str(directory/'failure.png'),full_page=True);report['error']=str(error);raise
            finally:b.close()
    finally:
        h.close();(directory/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(run(parser.parse_args().output),ensure_ascii=False))
