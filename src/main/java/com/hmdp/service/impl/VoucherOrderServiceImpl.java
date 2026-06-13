package com.hmdp.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.hmdp.dto.Result;
import com.hmdp.entity.VoucherOrder;
import com.hmdp.mapper.VoucherOrderMapper;
import com.hmdp.service.ISeckillVoucherService;
import com.hmdp.service.IVoucherOrderService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmdp.utils.RedisIdWorker;
import com.hmdp.utils.UserHolder;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.aop.framework.AopContext;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.connection.stream.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;
import javax.annotation.Resource;
import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;

/**
 * <p>
 * 服务实现类
 * </p>
 *
 * @author 虎哥
 * @since 2021-12-22
 */
@Service
@Slf4j
public class VoucherOrderServiceImpl extends ServiceImpl<VoucherOrderMapper, VoucherOrder> implements IVoucherOrderService {

    @Resource
    private ISeckillVoucherService iSeckillVoucherService;
    @Resource
    private RedisIdWorker redisIdWorker;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private RedissonClient redissonClient;

    private static final DefaultRedisScript<Long> SECKILL_SCRIPT;

    //redis+lua脚本，将下单业务放入stream消息队列
    static {
        SECKILL_SCRIPT = new DefaultRedisScript<>();
        SECKILL_SCRIPT.setLocation(new ClassPathResource("seckill.lua"));
        SECKILL_SCRIPT.setResultType(Long.class);
    }

    //定义一个线程池
    private static final ExecutorService SECKILL_ORDER_EXECUTOR = Executors.newSingleThreadExecutor();

    //启动服务后，自动执行VoucherOrderHandler，持续消费redis stream信息
    @PostConstruct
    private void init() {
        SECKILL_ORDER_EXECUTOR.submit(new VoucherOrderHandler());
    }

    @PreDestroy
    private void destroy() {
        SECKILL_ORDER_EXECUTOR.shutdownNow();
    }

    /**
     *生成全局唯一订单号，
     * 执行lua脚本，判断是否具有购买资格（库存是否充足，是否重复下单）
     * 有资格的话，扣减库存并将订单信息血热redis的stream消息队列
     * 接收lua脚本返回的结果（0：成功将订单信息写入消息队列；1：库存不足；2：重复购买）
     * @param voucherId
     * @return
     */
    @Override
    public Result seckillVoucher(Long voucherId) {
        //获取用户
        Long userId = UserHolder.getUser().getId();
        // 获取订单id
        long orderId = redisIdWorker.nextId("order");
        //1.执行stream + lua脚本-->判断是否有购买资格seckill.lua 有资格的话放入消息队列
        log.info("voucherId:{}",voucherId);
        Long result = stringRedisTemplate.execute(
                SECKILL_SCRIPT,
                Collections.emptyList(),
                voucherId.toString(), userId.toString(), String.valueOf(orderId)
        );
        //2.判断结果是否为0
        int r = result.intValue();
        if (r != 0) {
            //2.1不为0，没有购买资格
            return Result.fail(r == 1 ? "库存不足" : "不能重复下单");
        }
        //3.返回订单id
        return Result.ok(orderId);
    }

    private class VoucherOrderHandler implements Runnable {
        String queueName = "stream.orders";
        @Override
        public void run() {
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    //1.获取消息队列中订单信息XREADGROUP GROUP g1 c1 COUNT 1 BLOCK 2000 STREAMS stream.order >
                    //从stream.order中读取订单信息
                    List<MapRecord<String, Object, Object>> list = stringRedisTemplate.opsForStream().read(
                            Consumer.from("g1", "c1"),
                            StreamReadOptions.empty().count(1).block(Duration.ofSeconds(2)),
                            StreamOffset.create(queueName, ReadOffset.lastConsumed())
                    );
                    //2.判断消息获取是否成功
                    if (list == null || list.isEmpty()) {
                        //2.1如果获取失败，说明没有消息，继续下一次循环
                        continue;
                    }
                    //2.2.1解析消息中订单信息，将消息转为voucherOreder
                    MapRecord<String, Object, Object> record = list.get(0);
                    Map<Object, Object> values = record.getValue();
                    VoucherOrder voucherOrder = BeanUtil.fillBeanWithMap(values, new VoucherOrder(), true);
                    //2.2.2如果获取成功，可以下单
                    //调用handelVoucher执行下单
                    handelVoucherOrder(voucherOrder);
                    //3.ACK确认 stream.orders g1 id，确认订单已处理
                    stringRedisTemplate.opsForStream().acknowledge(queueName,"g1",record.getId());
                } catch (Exception e) {
                    if (Thread.currentThread().isInterrupted() || e instanceof IllegalStateException || e.getCause() instanceof IllegalStateException) {
                        log.info("Redis连接已关闭或线程被中断，VoucherOrderHandler退出。");
                        break;
                    }
                    log.error("处理订单异常！", e);
                    //用于处理未确认消息（已投递但未ack）
                    handlePendingList();
                }
            }
        }

        /**
         * 获取pending-list中订单信息
         * 如果获取失败，说明pending-list中没有异常消息，循环结束
         * 如果获取成功，可以下单并惊醒ack确认
         */
        private void handlePendingList() {
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    //1.获取pending-list中订单信息XREADGROUP GROUP g1 c1 COUNT 1 BLOCK 2000 STREAMS stream.order 0
                    List<MapRecord<String, Object, Object>> list = stringRedisTemplate.opsForStream().read(
                            Consumer.from("g1", "c1"),//消费者组g1 消费者c1
                            StreamReadOptions.empty().count(1),
                            StreamOffset.create(queueName, ReadOffset.from("0"))
                    );
                    //2.判断消息获取是否成功
                    if (list == null || list.isEmpty()) {
                        //2.1如果获取失败，说明pending-list没有异常消息，结束循环
                        break;
                    }
                    //2.2.1解析消息中订单信息
                    MapRecord<String, Object, Object> record = list.get(0);
                    Map<Object, Object> values = record.getValue();
                    VoucherOrder voucherOrder = BeanUtil.fillBeanWithMap(values, new VoucherOrder(), true);
                    //2.2.2如果获取成功，可以下单
                    handelVoucherOrder(voucherOrder);
                    //3.ACK确认 stream.orders g1 id
                    stringRedisTemplate.opsForStream().acknowledge(queueName,"g1",record.getId());
                } catch (Exception e) {
                    if (Thread.currentThread().isInterrupted() || e instanceof IllegalStateException || e.getCause() instanceof IllegalStateException) {
                        log.info("Redis连接已关闭或线程被中断，handlePendingList退出。");
                        break;
                    }
                    log.error("处理订pending-list单异常！", e);
                    try {
                        Thread.sleep(20);
                    } catch (InterruptedException interruptedException) {
                        log.info("Pending-list等待被中断。");
                        Thread.currentThread().interrupt();
                        break;
                    }
                }
            }
        }
    }

    /**
     * 加 redisson分布式锁，防止重复下单（一人一单）；
     * 调用代理对象写数据库
     * @param voucherOrder
     */
    private void handelVoucherOrder(VoucherOrder voucherOrder) {
        //1.获取用户
        Long userId = voucherOrder.getUserId();
        //2.创建锁对象  redission 分布式锁：可重入、可重试、主从一致性
        RLock lock = redissonClient.getLock("lock:order:" + userId);
        //3.获取锁
        boolean isLock = lock.tryLock();
        //4.判断是否成功获取锁
        if (!isLock) {
            //获取失败，返回错误信息或重试
            log.error("不允许重复下单！");
            return;
        }
        try {
            //调用代理对象写数据库，保证数据生效
            IVoucherOrderService proxy = (IVoucherOrderService) AopContext.currentProxy();
            proxy.createVoucherOrder(voucherOrder);
        } finally {
            //释放锁
            lock.unlock();
        }
    }


    /**
     * 查询用户是否已购买过，扣减库存并同步到数据库
     * @param voucherOrder
     */
    @Transactional
    public void createVoucherOrder(VoucherOrder voucherOrder) {
        //5.一人一单
        Long userId = voucherOrder.getUserId();
        Long voucherId = voucherOrder.getVoucherId();
        //5.1查询订单，判断是否是该用户的第一单
        int count = query().eq("user_id", userId)
                .eq("voucher_id", voucherId).count();
        //5.2判断是否存在
        if (count > 0) {
            //用户购买过
            log.error("用户已经购买过一次！");
            return;
        }
        //6.扣减库存  CAS乐观锁防止超卖
        boolean success = iSeckillVoucherService.update()
                .setSql("stock = stock - 1")//set stock = stock - 1
                .eq("voucher_id", voucherId)
                .gt("stock", 0)//where id = ? and stock > 0
                .update();
        if (!success) {
            //扣减失败
            log.error("库存不足！");
            return;
        }
        //7.创建订单
        save(voucherOrder);
    }
}
